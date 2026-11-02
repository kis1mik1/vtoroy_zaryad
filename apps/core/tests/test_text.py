from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.core import text

FORMS = ("объявление", "объявления", "объявлений")


@pytest.mark.parametrize(
    ("number", "expected"),
    [
        (0, "объявлений"),
        (1, "объявление"),
        (2, "объявления"),
        (4, "объявления"),
        (5, "объявлений"),
        (11, "объявлений"),
        (12, "объявлений"),
        (14, "объявлений"),
        (21, "объявление"),
        (22, "объявления"),
        (101, "объявление"),
        (111, "объявлений"),
        (1524, "объявления"),
    ],
)
def test_plural_form(number, expected):
    assert text.plural_form(number, FORMS) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (990, "990 ₽"),
        (12990, "12 990 ₽"),
        (1499990, "1 499 990 ₽"),
        (Decimal("12990.40"), "12 990 ₽"),
    ],
)
def test_format_price(value, expected):
    assert text.format_price(value) == expected


def _local(days_ago, hour=14, minute=30):
    day = timezone.localdate() - timedelta(days=days_ago)
    naive = datetime(day.year, day.month, day.day, hour, minute)
    return timezone.make_aware(naive)


def test_human_datetime_today_and_yesterday():
    assert text.human_datetime(_local(0)) == "сегодня в 14:30"
    assert text.human_datetime(_local(1, 9, 5)) == "вчера в 09:05"


def test_human_datetime_converts_to_local_timezone():
    moment = _local(0).astimezone(UTC)

    assert text.human_datetime(moment) == "сегодня в 14:30"


def test_human_datetime_other_day():
    today = timezone.localdate()
    value = timezone.make_aware(datetime(today.year - 1, 3, 12, 10, 0))

    assert text.human_datetime(value) == f"12 марта {today.year - 1}"


def test_human_datetime_same_year(monkeypatch):
    monkeypatch.setattr(timezone, "localdate", lambda: date(2026, 11, 2))
    value = timezone.make_aware(datetime(2026, 3, 12, 10, 0))

    assert text.human_datetime(value) == "12 марта в 10:00"


def test_human_datetime_accepts_date(monkeypatch):
    monkeypatch.setattr(timezone, "localdate", lambda: date(2026, 11, 2))

    assert text.human_datetime(date(2026, 11, 2)) == "сегодня"
    assert text.human_datetime(date(2026, 11, 1)) == "вчера"
    assert text.human_datetime(date(2026, 5, 9)) == "9 мая"
    assert text.human_datetime(date(2024, 5, 9)) == "9 мая 2024"
