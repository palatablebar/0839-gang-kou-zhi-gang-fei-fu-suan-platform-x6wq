from datetime import date

import pytest

from app.corrections.calendar import (
    CONFIRMED, PENDING, base_holidays, confirmed_holidays, parse_closures, tentative_holidays,
)
from app.errors import DomainIssue


def test_base_holidays_cover_national_days():
    holidays = base_holidays()
    assert date(2026, 10, 1) in holidays
    assert date(2026, 1, 1) in holidays
    assert date(2026, 11, 5) not in holidays


def test_parse_closures_accepts_two_statuses():
    records = parse_closures([
        {"date": "2026-11-05", "status": "confirmed", "note": "台风"},
        {"date": "2026-11-06", "status": "PENDING"},
    ])
    assert [item["status"] for item in records] == [CONFIRMED, PENDING]
    assert records[0]["date"] == "2026-11-05"


def test_parse_closures_rejects_bad_date():
    with pytest.raises(DomainIssue) as exc:
        parse_closures([{"date": "11/05", "status": "CONFIRMED"}])
    assert exc.value.code == "BAD_CLOSURE_DATE"


def test_parse_closures_rejects_unknown_status():
    with pytest.raises(DomainIssue) as exc:
        parse_closures([{"date": "2026-11-05", "status": "WAIT"}])
    assert exc.value.code == "BAD_CLOSURE_STATUS"


def test_holiday_views_split_by_status():
    records = parse_closures([
        {"date": "2026-11-05", "status": "CONFIRMED"},
        {"date": "2026-11-06", "status": "PENDING"},
    ])
    confirmed = confirmed_holidays(records)
    tentative = tentative_holidays(records)
    assert date(2026, 11, 5) in confirmed and date(2026, 11, 6) not in confirmed
    assert {date(2026, 11, 5), date(2026, 11, 6)} <= tentative
