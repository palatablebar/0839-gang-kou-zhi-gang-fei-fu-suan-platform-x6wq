"""休港日历与补证解析。

港方补送的休港日期分为 CONFIRMED（已确认，当天入账）与 PENDING（待核，
只用于判断同一箱是否会被再次改变）。基础法定假日保持不变，补证日期在其
之上叠加。记录对外统一使用 ISO 字符串，便于 JSON 持久化。
"""
from datetime import date

from app.domain.helpers import DAY
from app.errors import DomainIssue

CONFIRMED = "CONFIRMED"
PENDING = "PENDING"
STATUSES = (CONFIRMED, PENDING)


def base_holidays() -> set[date]:
    """初始批次使用的法定假日集合。"""
    return ({date(2026, 10, d) for d in range(1, 8)}
            | {date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)})


def parse_closures(records):
    """把补证中的休港日期记录规范化为 ISO 字符串字典列表。

    非法日期、缺失状态或未知状态直接拒收，避免坏数据进入复算。
    """
    if not isinstance(records, list):
        raise DomainIssue("BAD_REQUEST", detail="closures 必须是数组")
    parsed = []
    for index, raw in enumerate(records):
        if not isinstance(raw, dict):
            raise DomainIssue("BAD_REQUEST", detail=f"第 {index + 1} 条休港记录格式错误")
        try:
            day = DAY(raw.get("date"), "BAD_CLOSURE_DATE")
        except ValueError:
            raise DomainIssue("BAD_CLOSURE_DATE")
        status = str(raw.get("status", "")).strip().upper()
        if status not in STATUSES:
            raise DomainIssue("BAD_CLOSURE_STATUS")
        parsed.append({"date": day.isoformat(), "status": status,
                       "note": str(raw.get("note", "") or "")})
    parsed.sort(key=lambda item: (item["date"], item["status"]))
    return parsed


def _days(records, statuses) -> set[date]:
    return {date.fromisoformat(item["date"]) for item in records if item["status"] in statuses}


def confirmed_holidays(records) -> set[date]:
    """基础假日 + 所有已确认休港日。"""
    return base_holidays() | _days(records, (CONFIRMED,))


def tentative_holidays(records) -> set[date]:
    """基础假日 + 已确认与待核休港日（假设待核最终成立的上限视图）。"""
    return base_holidays() | _days(records, STATUSES)
