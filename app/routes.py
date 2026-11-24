import json

from flask import Blueprint, jsonify, request, send_file

from app.catalog import SPEC
from app.config import SAMPLES
from app.corrections import service as correction_service
from app.errors import DomainIssue
from app.evidence.render import render
from app.review.service import approve, create_run, serialize
from app.service import pipeline


api = Blueprint("api", __name__)
STAGE_INDEX = {"intake": 1, "prepare": 2, "calculate": 3, "decision": 4, "reconcile": 5}


def store():
    from flask import current_app
    return current_app.extensions["runs"]


def cstore():
    from flask import current_app
    return current_app.extensions["corrections"]


@api.get("/api/catalog")
def catalog():
    return jsonify(code=SPEC["code"], name=SPEC["name"], actor=SPEC["actor"], rule=SPEC["rule"],
                   rule_short=SPEC["rule_short"],
                   stages=[{"id": item, "name": name} for item, name in zip(
                       ["intake", "prepare", "calculate", "decision", "reconcile", "review", "evidence"],
                       SPEC["stages"])],
                   chart=SPEC["chart"], result_columns=SPEC["result_columns"],
                   columns=SPEC["columns"], samples=["dirty", "clean"])


@api.post("/api/stages/<stage_id>")
def stage(stage_id):
    if stage_id not in STAGE_INDEX:
        raise DomainIssue("STAGE_UNKNOWN", 404)
    data = request.get_json(silent=True) or {}
    profile = data.get("profile", "dirty")
    upto = SPEC["stages"][STAGE_INDEX[stage_id] - 1]
    return jsonify(pipeline(profile, upto=upto))


@api.post("/api/runs")
def create():
    data = request.get_json(silent=True) or {}
    profile = data.get("profile", "dirty")
    payload = pipeline(profile)
    return jsonify(create_run(store(), payload))


@api.get("/api/runs/<run_id>")
def get_run(run_id):
    run = serialize(store().get(run_id))
    if not run:
        raise DomainIssue("RUN_NOT_FOUND", 404)
    run["corrections"] = [
        {"correction_id": row["id"], "doc_id": row["doc_id"], "status": row["status"],
         "revision": row["revision"], "applied_run_revision": row["applied_run_revision"]}
        for row in cstore().list_for_run(run_id)
    ]
    run["evidence_versions"] = correction_service.evidence_versions(cstore(), run_id)
    return jsonify(run)


@api.post("/api/runs/<run_id>/review")
def review(run_id):
    data = request.get_json(silent=True) or {}
    if "decision" not in data or "expected_revision" not in data:
        raise DomainIssue("BAD_REQUEST")
    result = approve(store(), run_id, data["decision"], data.get("comment", ""), int(data["expected_revision"]))
    if data["decision"] == "APPROVED":
        # 原批次证据固化为 version 1，之后的更正依次追加，旧版原样保留。
        artifact = render(result)
        cstore().save_base_evidence(run_id, artifact, artifact["artifact_sha256"])
    return jsonify(result)


@api.get("/api/runs/<run_id>/evidence")
def evidence(run_id):
    run = serialize(store().get(run_id))
    if run is None:
        raise DomainIssue("RUN_NOT_FOUND", 404)
    if run["status"] != "APPROVED":
        raise DomainIssue("NOT_APPROVED", 409)
    # 已固化的首发凭证原样返回；尚未落库（旧数据）时即时渲染。
    frozen = cstore().get_evidence(run_id, 1)
    if frozen is not None:
        return jsonify(json.loads(frozen["artifact"]))
    return jsonify(render(run))


# ---------------------------------------------------------------------------
# 休港补证与复算更正
# ---------------------------------------------------------------------------

def _require_run(run_id):
    run_row = store().get(run_id)
    if run_row is None:
        raise DomainIssue("RUN_NOT_FOUND", 404)
    return run_row


@api.post("/api/runs/<run_id>/corrections")
def register_correction(run_id):
    run_row = _require_run(run_id)
    body = request.get_json(silent=True) or {}
    return jsonify(correction_service.register(cstore(), run_row, body))


@api.get("/api/runs/<run_id>/corrections")
def list_corrections(run_id):
    _require_run(run_id)
    rows = cstore().list_for_run(run_id)
    return jsonify([correction_service.serialize_correction(row) for row in rows])


@api.get("/api/runs/<run_id>/corrections/<correction_id>")
def get_correction(run_id, correction_id):
    _require_run(run_id)
    row = cstore().get(correction_id)
    if row is None or row["run_id"] != run_id:
        raise DomainIssue("CORRECTION_NOT_FOUND", 404)
    return jsonify(correction_service.serialize_correction(row, cstore().entries(correction_id)))


@api.post("/api/runs/<run_id>/corrections/<correction_id>/review")
def review_correction(run_id, correction_id):
    data = request.get_json(silent=True) or {}
    if "decision" not in data or "expected_revision" not in data:
        raise DomainIssue("BAD_REQUEST")
    result = correction_service.approve(
        cstore(), store(), run_id, correction_id, data["decision"],
        data.get("comment", ""), int(data["expected_revision"]))
    return jsonify(result)


@api.get("/api/runs/<run_id>/evidence/versions")
def evidence_versions(run_id):
    _require_run(run_id)
    return jsonify(correction_service.evidence_versions(cstore(), run_id))


@api.get("/api/runs/<run_id>/evidence/versions/<int:version>")
def evidence_version(run_id, version):
    _require_run(run_id)
    return jsonify(correction_service.evidence_at(cstore(), run_id, version))


@api.get("/api/examples/<profile>")
def example(profile):
    if profile not in {"clean", "dirty"}:
        raise DomainIssue("SAMPLE_UNKNOWN", 404)
    return send_file(SAMPLES / f"{profile}.csv", as_attachment=True)
