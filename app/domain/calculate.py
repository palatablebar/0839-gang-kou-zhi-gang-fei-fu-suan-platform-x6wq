from app.catalog import SPEC
from app.corrections.calendar import base_holidays
from app.domain.helpers import *  # noqa: F401,F403


def calculate_rows(items, holidays=None):
    out = []
    rows = items
    if holidays is None:
        holidays = base_holidays()
    for item in items:
        deadline = business_days_after(item["gate_in"], item["free_days"], holidays)
        charge_days = max(0, (item["gate_out"] - deadline).days)
        fee = tier_fee(charge_days)
        item["free_end"] = deadline.isoformat()
        item["charge_days"] = charge_days
        item["fee_cents"] = fee
        item["metric"] = D(str(fee), "CALC")
        item["limit"] = D("60000", "LIMIT")
        out.append(item)
    for item in out:
        item.setdefault("label", str(item.get(SPEC["key"], "")))
    return out
