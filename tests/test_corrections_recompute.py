from datetime import date

import pytest

from app.corrections.recompute import build_plan, ensure_bookable
from app.errors import DomainIssue


def base_rows():
    # C1: 进港 11-02（周一），3 个免堆工作日，原免堆截止 11-05，11-10 出场，原费 52000。
    return [
        {"container_id": "C1", "gate_in": date(2026, 11, 2), "gate_out": date(2026, 11, 10),
         "free_days": 3, "invoice_cents": 52000,
         "free_end": "2026-11-05", "charge_days": 5, "fee_cents": 52000},
        {"container_id": "C2", "gate_in": date(2026, 11, 6), "gate_out": date(2026, 11, 11),
         "free_days": 1, "invoice_cents": 16000,
         "free_end": "2026-11-09", "charge_days": 2, "fee_cents": 16000},
    ]


def entry(plan, cid):
    return next(item for item in plan["entries"] if item["container_id"] == cid)


def test_confirmed_closure_is_booked_same_day():
    plan = build_plan(base_rows(), [{"date": "2026-11-05", "status": "CONFIRMED", "note": "台风"}])
    c1 = entry(plan, "C1")
    assert c1["action"] == "BOOKED"
    # 免堆截止顺延到 11-06，计费天数 4，费用 38000，差额 -14000。
    assert c1["current_free_end"] == "2026-11-06"
    assert c1["current_fee_cents"] == 38000
    assert c1["booking_delta_cents"] == -14000
    assert plan["summary"]["balanced"] is True


def test_pending_closure_keeps_original_booking():
    plan = build_plan(base_rows(), [{"date": "2026-11-05", "status": "PENDING"}])
    c1 = entry(plan, "C1")
    assert c1["action"] == "HELD"
    assert c1["booking_delta_cents"] == 0
    # 现账视图仍等于原账；待核视图展示可能的变化。
    assert c1["current_fee_cents"] == 52000
    assert c1["tentative_fee_cents"] == 38000
    assert c1["held_by_pending"] is True


def test_mixed_confirmed_and_pending_holds_affected_container():
    plan = build_plan(base_rows(), [
        {"date": "2026-11-05", "status": "CONFIRMED"},
        {"date": "2026-11-06", "status": "PENDING"},
    ])
    c1 = entry(plan, "C1")
    # 待核日期会进一步改变免堆截止，整箱保留原账。
    assert c1["action"] == "HELD"
    assert c1["booking_delta_cents"] == 0
    assert c1["current_fee_cents"] == 38000
    assert c1["tentative_fee_cents"] == 8000


def test_irrelevant_closure_leaves_container_unchanged():
    # 11-05 休港不影响 11-06 才进港的 C2。
    plan = build_plan(base_rows(), [{"date": "2026-11-05", "status": "CONFIRMED"}])
    c2 = entry(plan, "C2")
    assert c2["action"] == "UNCHANGED"
    assert c2["booking_delta_cents"] == 0


def test_second_correction_delta_is_incremental():
    first = build_plan(base_rows(), [{"date": "2026-11-05", "status": "CONFIRMED"}])
    prior = {item["container_id"]: item["booking_delta_cents"]
             for item in first["entries"] if item["action"] == "BOOKED"}
    second = build_plan(base_rows(), [
        {"date": "2026-11-05", "status": "CONFIRMED"},
        {"date": "2026-11-06", "status": "CONFIRMED"},
    ], prior_deltas=prior)
    c1 = entry(second, "C1")
    # 总变化 52000 -> 8000 = -44000；第一次已记 -14000，本次增量 -30000。
    assert c1["booking_delta_cents"] == -30000
    assert c1["cumulative_delta_cents"] == -44000
    assert c1["cumulative_delta_cents"] == c1["current_fee_cents"] - c1["original_fee_cents"]
    assert second["summary"]["balanced"] is True


def test_cumulative_deltas_equal_final_fee_change():
    # 连续三次更正，每次加一个确认休港日，累计差额之和必须等于最终应收变化。
    closures, prior = [], {}
    totals = []
    for day in ("2026-11-04", "2026-11-05", "2026-11-06"):
        closures.append({"date": day, "status": "CONFIRMED"})
        plan = build_plan(base_rows(), closures, prior_deltas=prior)
        c1 = entry(plan, "C1")
        if c1["action"] == "BOOKED":
            totals.append(c1["booking_delta_cents"])
            prior[c1["container_id"]] = c1["cumulative_delta_cents"]
        assert plan["summary"]["balanced"] is True
    final = entry(plan, "C1")
    assert sum(totals) == final["current_fee_cents"] - final["original_fee_cents"]


def test_bookable_gate_blocks_held_container():
    plan = build_plan(base_rows(), [{"date": "2026-11-05", "status": "PENDING"}])
    with pytest.raises(DomainIssue) as exc:
        ensure_bookable(plan)
    assert exc.value.code == "CORRECTION_PENDING_HELD"


def test_bookable_gate_passes_when_no_hold():
    plan = build_plan(base_rows(), [{"date": "2026-11-05", "status": "CONFIRMED"}])
    ensure_bookable(plan)  # 不抛异常即通过
