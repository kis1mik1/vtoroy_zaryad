from datetime import date, datetime
from decimal import Decimal

from django.utils import timezone
from django.utils.text import slugify

NBSP = "\u00a0"
NARROW_NBSP = "\u202f"

MONTHS_GENITIVE = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)


def plural_form(number: int, forms: tuple[str, str, str] | list[str]) -> str:
    one, few, many = forms
    number = abs(int(number))
    if number % 10 == 1 and number % 100 != 11:
        return one
    if 2 <= number % 10 <= 4 and not 12 <= number % 100 <= 14:
        return few
    return many


def format_number(value: int | float | Decimal) -> str:
    rounded = round(Decimal(value))
    return f"{rounded:,}".replace(",", NARROW_NBSP)


def format_price(value: int | float | Decimal) -> str:
    return f"{format_number(value)}{NBSP}₽"


def format_day(value: date, *, with_year: bool | None = None) -> str:
    if with_year is None:
        with_year = value.year != timezone.localdate().year
    text = f"{value.day}{NBSP}{MONTHS_GENITIVE[value.month - 1]}"
    return f"{text} {value.year}" if with_year else text


def human_datetime(value: datetime | date) -> str:
    today = timezone.localdate()
    if isinstance(value, datetime):
        moment = timezone.localtime(value) if timezone.is_aware(value) else value
        day, time = moment.date(), f"{moment:%H:%M}"
    else:
        day, time = value, None

    if day == today:
        label = "сегодня"
    elif (today - day).days == 1:
        label = "вчера"
    else:
        label = format_day(day)
        if day.year != today.year or time is None:
            return label
    return f"{label} в {time}" if time else label


TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya",
}  # fmt: skip


def slugify_ru(value: str, max_length: int = 80) -> str:
    latin = "".join(TRANSLIT.get(char, char) for char in value.lower())
    return slugify(latin)[:max_length].strip("-")
