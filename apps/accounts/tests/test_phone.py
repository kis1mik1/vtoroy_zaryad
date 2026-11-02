import pytest
from django.core.exceptions import ValidationError

from apps.accounts.phone import format_phone, normalize_phone


@pytest.mark.parametrize(
    "raw",
    ["+7 914 123-45-67", "8 (914) 123-45-67", "89141234567", "9141234567", " +79141234567 "],
)
def test_normalize_phone(raw):
    assert normalize_phone(raw) == "+79141234567"


def test_empty_phone_allowed():
    assert normalize_phone("  ") == ""


@pytest.mark.parametrize("raw", ["12345", "+1 202 555 0100", "8 423 222-33-44", "914 abc 45 67"])
def test_invalid_phone(raw):
    with pytest.raises(ValidationError):
        normalize_phone(raw)


def test_format_phone():
    assert format_phone("+79141234567") == "+7 914 123-45-67"
    assert format_phone("") == ""
