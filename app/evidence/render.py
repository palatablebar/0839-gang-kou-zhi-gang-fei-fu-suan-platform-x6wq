from app.errors import DomainIssue
from app.evidence.manifest import stable_digest


def build_artifact(run_payload, run_row):
    """构造原批次证据主体（不含摘要），供原证据与更正证据复用。"""
    return {
        "schema": "workbench-evidence/v1",
        "run_id": run_row["id"],
        "project": run_payload["project"],
        "rule": run_payload["rule"],
        "profile": run_payload["profile"],
        "source": run_payload["source"],
        "counts": run_payload["counts"],
        "ledger": run_payload["ledger"],
        "summary": run_payload["summary"],
        "review": {"status": run_row["status"], "revision": run_row["revision"], "comment": run_row["comment"]},
    }


def render(run):
    if run is None:
        raise DomainIssue("RUN_NOT_FOUND", 404)
    if run["status"] != "APPROVED":
        raise DomainIssue("NOT_APPROVED", 409)
    run_row = {"id": run["run_id"], "status": run["status"],
               "revision": run["revision"], "comment": run["comment"]}
    artifact = build_artifact(run, run_row)
    artifact["artifact_sha256"] = stable_digest(artifact)
    return artifact
