import re

from django.core.exceptions import ValidationError

INVALID_PHONE = "Укажите российский номер мобильного: +7 и 10 цифр."


def normalize_phone(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    if re.search(r"[^\d\s()+\-]", raw):
        raise ValidationError(INVALID_PHONE, code="invalid_phone")
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 10:
        digits = f"7{digits}"
    elif len(digits) == 11 and digits[0] in "78":
        digits = f"7{digits[1:]}"
    else:
        raise ValidationError(INVALID_PHONE, code="invalid_phone")
    if digits[1] != "9":
        raise ValidationError(INVALID_PHONE, code="invalid_phone")
    return f"+{digits}"


def format_phone(phone: str) -> str:
    if not re.fullmatch(r"\+7\d{10}", phone or ""):
        return phone or ""
    d = phone[2:]
    return f"+7 {d[:3]} {d[3:6]}-{d[6:8]}-{d[8:]}"
