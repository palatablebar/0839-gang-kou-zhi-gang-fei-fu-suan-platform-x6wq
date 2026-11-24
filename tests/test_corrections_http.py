"""复算更正端到端测试：入账、保留原账、守恒、幂等、版本证据。"""


def approved_run(client):
    run = client.post("/api/runs", json={"profile": "clean"}).get_json()
    client.post(f"/api/runs/{run['run_id']}/review",
                json={"decision": "APPROVED", "comment": "首发", "expected_revision": 0})
    return run["run_id"]


def register(client, run_id, doc_id, closures):
    return client.post(f"/api/runs/{run_id}/corrections",
                       json={"doc_id": doc_id, "closures": closures})


def review(client, run_id, correction_id, revision, decision="APPROVED", comment="更正"):
    return client.post(f"/api/runs/{run_id}/corrections/{correction_id}/review",
                       json={"decision": decision, "comment": comment,
                             "expected_revision": revision})


def test_confirmed_closure_registers_bookable_plan(client):
    run_id = approved_run(client)
    response = register(client, run_id, "SUP-1", [{"date": "2026-11-05", "status": "CONFIRMED"}])
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "DRAFT"
    assert data["plan"]["summary"]["held"] == 0
    assert data["plan"]["summary"]["booked"] == 1
    c1 = next(item for item in data["plan"]["entries"] if item["container_id"] == "C1")
    assert c1["booking_delta_cents"] == -14000


def test_pending_closure_holds_container_and_blocks_approval(client):
    run_id = approved_run(client)
    data = register(client, run_id, "SUP-1", [{"date": "2026-11-05", "status": "PENDING"}]).get_json()
    assert data["plan"]["summary"]["held"] >= 1
    blocked = review(client, run_id, data["correction_id"], 0)
    assert blocked.status_code == 409
    assert blocked.get_json()["code"] == "CORRECTION_PENDING_HELD"
    # 签发失败：更正仍是 DRAFT，运行版本与证据保持旧版。
    run = client.get(f"/api/runs/{run_id}").get_json()
    assert run["revision"] == 1
    assert [item["version"] for item in run["evidence_versions"]] == [1]
    stored = client.get(f"/api/runs/{run_id}/corrections/{data['correction_id']}").get_json()
    assert stored["status"] == "DRAFT"


def test_rerun_same_supplement_is_idempotent(client):
    run_id = approved_run(client)
    body = {"doc_id": "SUP-1", "closures": [{"date": "2026-11-05", "status": "CONFIRMED"}]}
    first = client.post(f"/api/runs/{run_id}/corrections", json=body).get_json()
    second = client.post(f"/api/runs/{run_id}/corrections", json=body).get_json()
    assert first["correction_id"] == second["correction_id"]
    assert second["created"] is False
    assert len(client.get(f"/api/runs/{run_id}/corrections").get_json()) == 1


def test_same_doc_id_with_changed_content_is_conflict(client):
    run_id = approved_run(client)
    register(client, run_id, "SUP-1", [{"date": "2026-11-05", "status": "CONFIRMED"}])
    conflict = register(client, run_id, "SUP-1", [{"date": "2026-11-06", "status": "CONFIRMED"}])
    assert conflict.status_code == 409
    assert conflict.get_json()["code"] == "DOC_CONTENT_CONFLICT"
    # 原登记未被覆盖。
    stored = client.get(f"/api/runs/{run_id}/corrections").get_json()
    assert len(stored) == 1
    assert stored[0]["plan"]["closures"][0]["date"] == "2026-11-05"


def test_successful_approval_bumps_revision_and_freezes_evidence(client):
    run_id = approved_run(client)
    data = register(client, run_id, "SUP-1", [{"date": "2026-11-05", "status": "CONFIRMED"}]).get_json()
    result = review(client, run_id, data["correction_id"], 0)
    assert result.status_code == 200
    assert result.get_json()["status"] == "APPROVED"
    run = client.get(f"/api/runs/{run_id}").get_json()
    assert run["revision"] == 2
    versions = run["evidence_versions"]
    assert [item["version"] for item in versions] == [1, 2]
    v1 = client.get(f"/api/runs/{run_id}/evidence/versions/1").get_json()
    v2 = client.get(f"/api/runs/{run_id}/evidence/versions/2").get_json()
    assert v1["schema"] == "workbench-evidence/v1"
    assert v2["schema"] == "workbench-correction/v1"
    assert v2["doc_id"] == "SUP-1"
    assert v2["run_revision"] == 2
    assert v2["review"]["revision"] == 2
    assert v2["artifact_sha256"] == versions[1]["digest"]


def test_legacy_evidence_endpoint_keeps_original_artifact(client):
    run_id = approved_run(client)
    original = client.get(f"/api/runs/{run_id}/evidence").get_json()
    data = register(client, run_id, "SUP-1", [{"date": "2026-11-05", "status": "CONFIRMED"}]).get_json()
    review(client, run_id, data["correction_id"], 0)
    again = client.get(f"/api/runs/{run_id}/evidence").get_json()
    assert again == original
    frozen = client.get(f"/api/runs/{run_id}/evidence/versions/1").get_json()
    assert frozen == original


def test_old_evidence_versions_remain_downloadable_and_immutable(client):
    run_id = approved_run(client)
    first = register(client, run_id, "SUP-1", [{"date": "2026-11-05", "status": "CONFIRMED"}]).get_json()
    review(client, run_id, first["correction_id"], 0)
    second = register(client, run_id, "SUP-2", [{"date": "2026-11-06", "status": "CONFIRMED"}]).get_json()
    review(client, run_id, second["correction_id"], 0)
    v2_before = client.get(f"/api/runs/{run_id}/evidence/versions/2").get_json()
    v3 = client.get(f"/api/runs/{run_id}/evidence/versions/3").get_json()
    v2_after = client.get(f"/api/runs/{run_id}/evidence/versions/2").get_json()
    assert v2_before == v2_after
    assert v3["doc_id"] == "SUP-2"
    assert client.get(f"/api/runs/{run_id}/evidence/versions/99").status_code == 404


def test_cumulative_deltas_match_final_fee_change(client):
    run_id = approved_run(client)
    first = register(client, run_id, "SUP-1", [{"date": "2026-11-05", "status": "CONFIRMED"}]).get_json()
    review(client, run_id, first["correction_id"], 0)
    second = register(client, run_id, "SUP-2", [
        {"date": "2026-11-05", "status": "CONFIRMED"},
        {"date": "2026-11-06", "status": "CONFIRMED"},
    ]).get_json()
    review(client, run_id, second["correction_id"], 0)
    v2 = client.get(f"/api/runs/{run_id}/evidence/versions/2").get_json()
    v3 = client.get(f"/api/runs/{run_id}/evidence/versions/3").get_json()
    c1_v2 = next(item for item in v2["entries"] if item["container_id"] == "C1")
    c1_v3 = next(item for item in v3["entries"] if item["container_id"] == "C1")
    total_delta = c1_v2["booking_delta_cents"] + c1_v3["booking_delta_cents"]
    final_change = c1_v3["current_fee_cents"] - c1_v3["original_fee_cents"]
    assert total_delta == final_change
    assert c1_v3["cumulative_delta_cents"] == final_change


def test_stale_correction_revision_is_rejected_without_changes(client):
    run_id = approved_run(client)
    data = register(client, run_id, "SUP-1", [{"date": "2026-11-05", "status": "CONFIRMED"}]).get_json()
    assert review(client, run_id, data["correction_id"], 0).status_code == 200
    stale = review(client, run_id, data["correction_id"], 0)
    assert stale.status_code == 409
    assert stale.get_json()["code"] == "STALE_REVIEW"


def test_pending_then_confirmed_releases_held_container(client):
    run_id = approved_run(client)
    pending = register(client, run_id, "SUP-1", [{"date": "2026-11-05", "status": "PENDING"}]).get_json()
    assert review(client, run_id, pending["correction_id"], 0).status_code == 409
    confirmed = register(client, run_id, "SUP-2", [
        {"date": "2026-11-05", "status": "PENDING"},
        {"date": "2026-11-05", "status": "CONFIRMED", "note": "核对完成"},
    ]).get_json()
    assert confirmed["plan"]["summary"]["held"] == 0
    assert review(client, run_id, confirmed["correction_id"], 0).status_code == 200


def test_held_decision_does_not_book_or_bump_revision(client):
    run_id = approved_run(client)
    data = register(client, run_id, "SUP-1", [{"date": "2026-11-05", "status": "PENDING"}]).get_json()
    result = review(client, run_id, data["correction_id"], 0, decision="HELD", comment="先保留原账")
    assert result.status_code == 200
    assert result.get_json()["status"] == "HELD"
    run = client.get(f"/api/runs/{run_id}").get_json()
    assert run["revision"] == 1
    assert len(run["evidence_versions"]) == 1


def test_correction_requires_approved_run(client):
    run = client.post("/api/runs", json={"profile": "clean"}).get_json()
    data = register(client, run["run_id"], "SUP-1", [{"date": "2026-11-05", "status": "CONFIRMED"}]).get_json()
    response = review(client, run["run_id"], data["correction_id"], 0)
    assert response.status_code == 409
    assert response.get_json()["code"] == "NOT_APPROVED"


def test_validation_errors(client):
    run_id = approved_run(client)
    bad_date = client.post(f"/api/runs/{run_id}/corrections",
                           json={"doc_id": "X", "closures": [{"date": "nope", "status": "CONFIRMED"}]})
    assert bad_date.status_code == 400
    assert bad_date.get_json()["code"] == "BAD_CLOSURE_DATE"
    bad_status = client.post(f"/api/runs/{run_id}/corrections",
                             json={"doc_id": "X", "closures": [{"date": "2026-11-05", "status": "WAIT"}]})
    assert bad_status.get_json()["code"] == "BAD_CLOSURE_STATUS"
    no_doc = client.post(f"/api/runs/{run_id}/corrections",
                         json={"closures": [{"date": "2026-11-05", "status": "CONFIRMED"}]})
    assert no_doc.get_json()["code"] == "DOC_ID_MISSING"
    empty = client.post(f"/api/runs/{run_id}/corrections", json={"doc_id": "X", "closures": []})
    assert empty.get_json()["code"] == "CLOSURES_EMPTY"


def test_unknown_run_and_correction_return_404(client):
    assert client.post("/api/runs/missing/corrections",
                       json={"doc_id": "X", "closures": [{"date": "2026-11-05", "status": "CONFIRMED"}]}
                       ).status_code == 404
    run_id = approved_run(client)
    assert client.get(f"/api/runs/{run_id}/corrections/nope").status_code == 404


def test_multi_container_booking_delta_conserves(client):
    run_id = approved_run(client)
    # 2026-11-09（周一）休港只改变 C2 的免堆截止，C1 不受影响。
    data = register(client, run_id, "SUP-M", [{"date": "2026-11-09", "status": "CONFIRMED"}]).get_json()
    summary = data["plan"]["summary"]
    assert summary["booked"] == 1 and summary["balanced"] is True
    c2 = next(item for item in data["plan"]["entries"] if item["container_id"] == "C2")
    assert c2["booking_delta_cents"] == -8000
    assert review(client, run_id, data["correction_id"], 0).status_code == 200
    artifact = client.get(f"/api/runs/{run_id}/evidence/versions/2").get_json()
    booked_entries = [item for item in artifact["entries"] if item["action"] == "BOOKED"]
    assert sum(item["booking_delta_cents"] for item in booked_entries) == -8000
