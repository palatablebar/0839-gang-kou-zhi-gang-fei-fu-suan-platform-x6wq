"""休港补证驱动的滞港费复算与更正计划。

入账原则（对应业务要求）：
- 已确认休港日当天参与复算；产生差额且不受待核日期影响的箱子立刻入账。
- 待核日期若会改变某箱的免堆截止日或应收金额，该箱保留原账，不记差额。
- 同一箱多次更正的累计差额必须等于当前应收相对原账的变化（守恒校验）。
"""
from app.corrections.calendar import CONFIRMED, PENDING, confirmed_holidays, parse_closures, tentative_holidays
from app.domain.helpers import business_days_after, tier_fee
from app.errors import DomainIssue


def _recalc(container, holidays):
    """按给定假日集合复算单箱，返回复算快照。"""
    deadline = business_days_after(container["gate_in"], container["free_days"], holidays)
    charge_days = max(0, (container["gate_out"] - deadline).days)
    fee = tier_fee(charge_days)
    return {"free_end": deadline.isoformat(), "charge_days": charge_days, "fee_cents": fee}


def _changed(before, after):
    return (before["free_end"] != after["free_end"]
            or before["charge_days"] != after["charge_days"]
            or before["fee_cents"] != after["fee_cents"])


def build_plan(base_rows, closure_records, prior_deltas=None):
    """依据当前全部补证生成更正计划。

    base_rows: 原始批次已采信的箱单（含 gate_in/gate_out/free_days 与原账 fee_cents）。
    closure_records: 原始补证记录列表，先经 parse_closures 校验。
    prior_deltas: 该箱历次已签发更正的累计差额（用于计算本次增量）。
    返回每个箱子的原账、确认视图、含待核视图、记账动作与守恒校验结果。
    """
    records = parse_closures(closure_records)
    prior_deltas = prior_deltas or {}
    confirmed = confirmed_holidays(records)
    tentative = tentative_holidays(records)
    entries = []

    for row in base_rows:
        cid = row["container_id"]
        original = {
            "free_end": row["free_end"],
            "charge_days": row["charge_days"],
            "fee_cents": row["fee_cents"],
        }
        on_confirmed = _recalc(row, confirmed)
        on_tentative = _recalc(row, tentative)
        # 待核日期若成立会进一步改变该箱，则保留原账等待核对完成。
        held = _changed(on_confirmed, on_tentative)
        total_change = on_confirmed["fee_cents"] - original["fee_cents"]
        # 本次记账增量 = 当前应收相对原账的总变化 − 历次已入账差额。
        incremental = total_change - prior_deltas.get(cid, 0)
        if held:
            action = "HELD"
        elif incremental != 0:
            action = "BOOKED"
        else:
            action = "UNCHANGED"
        entries.append({
            "container_id": cid,
            "action": action,
            "original_fee_cents": original["fee_cents"],
            "current_fee_cents": on_confirmed["fee_cents"],
            "booking_delta_cents": 0 if held else incremental,
            "cumulative_delta_cents": prior_deltas.get(cid, 0) + (0 if held else incremental),
            "original_free_end": original["free_end"],
            "current_free_end": on_confirmed["free_end"],
            "original_charge_days": original["charge_days"],
            "current_charge_days": on_confirmed["charge_days"],
            "tentative_free_end": on_tentative["free_end"],
            "tentative_fee_cents": on_tentative["fee_cents"],
            "held_by_pending": held,
        })

    booked = [item for item in entries if item["action"] == "BOOKED"]
    held_rows = [item for item in entries if item["action"] == "HELD"]
    delta_total = sum(item["booking_delta_cents"] for item in booked)
    # 守恒：入账箱的累计差额（历史 + 本次）必须等于当前应收相对原账的变化；
    # HELD 箱刻意保留原账，其确认视图变化待待核日期落定后再处理，不参与本版守恒。
    balanced = all(item["cumulative_delta_cents"]
                   == item["current_fee_cents"] - item["original_fee_cents"]
                   for item in entries if item["action"] != "HELD")
    summary = {
        "containers": len(entries),
        "booked": len(booked),
        "held": len(held_rows),
        "unchanged": len(entries) - len(booked) - len(held_rows),
        "booking_delta_total_cents": delta_total,
        "balanced": balanced,
        "closure_confirmed": sum(1 for item in records if item["status"] == CONFIRMED),
        "closure_pending": sum(1 for item in records if item["status"] == PENDING),
    }
    return {"entries": entries, "summary": summary, "closures": records}


def ensure_bookable(plan):
    """签发前置闸门：守恒成立且不存在待核保留箱。"""
    if not plan["summary"]["balanced"]:
        raise DomainIssue("CORRECTION_UNBALANCED", 409)
    if plan["summary"]["held"]:
        raise DomainIssue("CORRECTION_PENDING_HELD", 409)
