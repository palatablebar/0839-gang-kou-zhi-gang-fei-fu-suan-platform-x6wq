"""复算更正应用服务：补证登记、累计守恒、签发与证据版本。"""
import hashlib
import json

from app.corrections.calendar import parse_closures
from app.corrections.recompute import build_plan, ensure_bookable
from app.domain.helpers import DAY
from app.errors import DomainIssue
from app.evidence.manifest import stable_digest
from app.evidence.render import build_artifact


def request_fingerprint(closures):
    """补证内容指纹：同 doc_id 但内容不同视为冲突，避免覆盖原登记。"""
    return hashlib.sha256(
        json.dumps(closures, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def serialize_correction(row, entries=None):
    if row is None:
        return None
    data = {
        "correction_id": row["id"],
        "run_id": row["run_id"],
        "doc_id": row["doc_id"],
        "status": row["status"],
        "revision": row["revision"],
        "comment": row["comment"],
        "created_at": row["created_at"],
        "expected_run_revision": row["expected_run_revision"],
        "applied_run_revision": row["applied_run_revision"],
        "plan": json.loads(row["plan"]),
    }
    if entries is not None:
        data["entries"] = [json.loads(item["detail"]) for item in entries]
    return data


def base_rows(run_payload):
    """从批次存档重建原始已采信箱单，并恢复日期类型供复算使用。"""
    rows = []
    for item in run_payload.get("base_rows", []):
        rows.append({
            "container_id": item["container_id"],
            "gate_in": DAY(item["gate_in"], "BAD_DATE"),
            "gate_out": DAY(item["gate_out"], "BAD_DATE"),
            "free_days": int(item["free_days"]),
            "invoice_cents": int(item["invoice_cents"]),
            "free_end": item["free_end"],
            "charge_days": int(item["charge_days"]),
            "fee_cents": int(item["fee_cents"]),
        })
    if not rows:
        raise DomainIssue("RUN_NO_BASE_ROWS", 409)
    return rows


def _closure_records(cstore, run_id, incoming):
    """已登记补证 + 本次补证，全部参与复算视图。"""
    records = []
    for row in cstore.list_for_run(run_id):
        records.extend(json.loads(row["payload"])["closures"])
    records.extend(incoming)
    return records


def register(cstore, run_row, body):
    """登记一份休港补证并生成更正计划（重跑同 doc_id 幂等返回）。"""
    doc_id = str(body.get("doc_id", "")).strip()
    if not doc_id:
        raise DomainIssue("DOC_ID_MISSING")
    closures = body.get("closures")
    if not isinstance(closures, list) or not closures:
        raise DomainIssue("CLOSURES_EMPTY")
    run_payload = json.loads(run_row["payload"])
    rows = base_rows(run_payload)
    incoming = parse_closures(closures)
    prior = cstore.approved_deltas(run_row["id"])
    plan = build_plan(rows, _closure_records(cstore, run_row["id"], incoming), prior_deltas=prior)
    payload = {"doc_id": doc_id, "closures": plan["closures"],
               "fingerprint": request_fingerprint(incoming)}
    existing = cstore.find_doc(run_row["id"], doc_id)
    if existing is not None:
        old_payload = json.loads(existing["payload"])
        if old_payload.get("fingerprint") != payload["fingerprint"]:
            raise DomainIssue("DOC_CONTENT_CONFLICT", 409)
    row, created = cstore.create_draft(run_row["id"], doc_id, run_row["revision"], plan, payload)
    out = serialize_correction(row, cstore.entries(row["id"]))
    out["created"] = created
    return out


def cumulative_check(cstore, run_id, plan):
    """累计守恒校验。

    每次更正的 booking_delta 是相对上一版现账的增量；同一箱历次已入账差额
    与本次增量之和，必须等于当前应收相对原账的总变化。
    """
    prior = cstore.approved_deltas(run_id)
    problems = []
    for entry in plan["entries"]:
        cid = entry["container_id"]
        if entry["action"] == "HELD":
            # 待核保留箱本版不记账，跳过累计校验，待日期落定后再核算。
            continue
        expected_total = entry["current_fee_cents"] - entry["original_fee_cents"]
        if entry["action"] == "BOOKED":
            booked_total = prior.get(cid, 0) + entry["booking_delta_cents"]
            if booked_total != expected_total:
                problems.append({"container_id": cid, "booked_total": booked_total,
                                 "expected": expected_total})
        elif prior.get(cid, 0) != expected_total:
            # 本次不记账的箱子，历史累计差额仍须与当前总变化一致。
            problems.append({"container_id": cid, "booked_total": prior.get(cid, 0),
                             "expected": expected_total})
    return problems


def approve(cstore, runs_store, run_id, correction_id, decision, comment, expected_revision):
    row = cstore.get(correction_id)
    if row is None or row["run_id"] != run_id:
        raise DomainIssue("CORRECTION_NOT_FOUND", 404)
    if decision not in {"APPROVED", "HELD"}:
        raise DomainIssue("BAD_REQUEST")
    # 版本号先于业务闸门校验，失败时旧版原样保留，不产生任何账。
    if row["revision"] != expected_revision:
        raise DomainIssue("STALE_REVIEW", 409)
    run_row = runs_store.get(run_id)
    if run_row is None:
        raise DomainIssue("RUN_NOT_FOUND", 404)
    if run_row["status"] != "APPROVED":
        raise DomainIssue("NOT_APPROVED", 409)
    if run_row["revision"] != row["expected_run_revision"]:
        raise DomainIssue("STALE_REVIEW", 409, detail="原批次已有更新版本，请基于最新版本复核")
    plan = json.loads(row["plan"])
    if decision == "APPROVED":
        ensure_bookable(plan)
        problems = cumulative_check(cstore, run_id, plan)
        if problems:
            raise DomainIssue("CORRECTION_UNBALANCED", 409, detail=json.dumps(problems, ensure_ascii=False))

    artifact, digest = None, None
    if decision == "APPROVED":
        artifact = correction_artifact(run_row, row, plan)
        digest = artifact["artifact_sha256"]
    updated, problem = cstore.approve(run_id, correction_id, decision, comment, expected_revision,
                                       run_row["revision"], plan, artifact, digest)
    if problem == "missing":
        raise DomainIssue("CORRECTION_NOT_FOUND", 404)
    if problem in {"stale", "run_stale"}:
        raise DomainIssue("STALE_REVIEW", 409)
    if problem == "run_missing":
        raise DomainIssue("RUN_NOT_FOUND", 404)
    return serialize_correction(updated, cstore.entries(correction_id))


def correction_artifact(run_row, correction_row, plan):
    """签发证据：记录补证、逐箱差额与累计守恒，附稳定摘要。"""
    run_payload = json.loads(run_row["payload"])
    artifact = build_artifact(run_payload, run_row)
    new_run_revision = run_row["revision"] + 1
    # 证据反映签发后的运行版本，与 correction_evidence.version 保持一致。
    artifact["review"] = {"status": "APPROVED", "revision": new_run_revision,
                          "comment": run_row["comment"]}
    artifact["schema"] = "workbench-correction/v1"
    artifact["correction_id"] = correction_row["id"]
    artifact["doc_id"] = correction_row["doc_id"]
    artifact["base_revision"] = correction_row["expected_run_revision"]
    artifact["correction_revision"] = correction_row["revision"] + 1
    artifact["run_revision"] = new_run_revision
    artifact["closure_summary"] = plan["summary"]
    artifact["entries"] = plan["entries"]
    artifact["artifact_sha256"] = stable_digest(artifact)
    return artifact


def evidence_versions(cstore, run_id):
    return cstore.list_evidence(run_id)


def evidence_at(cstore, run_id, version):
    row = cstore.get_evidence(run_id, version)
    if row is None:
        raise DomainIssue("EVIDENCE_NOT_FOUND", 404)
    return json.loads(row["artifact"])
