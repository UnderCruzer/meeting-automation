from datetime import date

import pytest

from app.services.due_dates import parse_due

REF = date(2026, 10, 1)  # Thursday


@pytest.mark.parametrize("text,expected", [
    ("2026-10-10", date(2026, 10, 10)),
    ("2026.10.10", date(2026, 10, 10)),
    ("2026년 10월 10일", date(2026, 10, 10)),
    ("10/10", date(2026, 10, 10)),
    ("10.15", date(2026, 10, 15)),
    ("10월 20일까지", date(2026, 10, 20)),
    ("~7/3", date(2027, 7, 3)),          # long past in this year → next year
    ("9/20", date(2026, 9, 20)),         # recently passed → stays (overdue)
    ("1/5", date(2027, 1, 5)),
    ("오늘", date(2026, 10, 1)),
    ("내일 오전", date(2026, 10, 2)),
    ("모레", date(2026, 10, 3)),
    ("금요일", date(2026, 10, 2)),
    ("화요일", date(2026, 10, 6)),        # bare weekday already passed → next one
    ("이번 주 금요일", date(2026, 10, 2)),
    ("다음 주 수요일", date(2026, 10, 7)),
    ("다다음주 월요일", date(2026, 10, 12)),
])
def test_parses_common_formats(text, expected):
    assert parse_due(text, REF) == expected


@pytest.mark.parametrize("text", ["", None, "미정", "ASAP", "다음 스프린트", "2/30", "13/1"])
def test_unknown_or_invalid_is_none(text):
    assert parse_due(text, REF) is None
