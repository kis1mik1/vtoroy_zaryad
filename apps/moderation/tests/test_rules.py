import pytest

from apps.ads.models import PriceStat
from apps.ads.tests.helpers import publish
from apps.moderation.rules import REJECT, REVIEW, check_rules, text_flags
from apps.moderation.text import normalize

pytestmark = pytest.mark.django_db


def codes(text: str) -> set[str]:
    return {flag.code for flag in text_flags(normalize(text))}


def test_normalize_reveals_obfuscated_words():
    assert normalize("Пишите в Тeлeгрaм") == "пишите в телеграм"
    assert normalize("т е л е г р а м, ВАТСАП") == "телеграм, ватсап"
    assert normalize("Ёмкость 87%") == "емкость 87%"
    assert normalize("iPhone 13 Pro") == "iphone 13 pro"


@pytest.mark.parametrize(
    "text",
    [
        "Звоните +7 914 123-45-67",
        "звоните 89141234567 после шести",
        "тел. 8 (423) 222-33-44",
        "мой номер 914 123 45 67",
    ],
)
def test_phone_numbers_found(text):
    assert "phone" in codes(text)


@pytest.mark.parametrize(
    "text",
    [
        "128 ГБ, 8 ГБ ОЗУ, 2023 год, батарея 4500 мАч",
        "IMEI 356789012345678, серийный номер на коробке",
        "Цена 89 900, торг",
    ],
)
def test_numbers_that_are_not_phones(text):
    assert "phone" not in codes(text)


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("пишите на ivan.petrov@mail.ru", "email"),
        ("подробнее на avito.ru/vladivostok", "link"),
        ("каталог: https://shop.example.com/phones", "link"),
        ("мой канал t.me/gadgets_vl", "link"),
        ("ник в тг @gadget_seller", "handle"),
        ("пишите в вотсап", "messenger"),
        ("Пишите в Тeлeгрaм", "messenger"),
    ],
)
def test_contacts_and_links(text, code):
    assert code in codes(text)


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("Продам травмат и патроны", "weapons"),
        ("скрытая камера в виде зарядки", "spy"),
        ("глушилка сотовой связи", "spy"),
        ("антибиотики и другие лекарства", "drugs"),
        ("айфон заблокирован по imei, на запчасти", "locked"),
        ("icloud lock, продаю как есть", "locked"),
        ("телефон привязан к чужому аккаунту", "locked"),
    ],
)
def test_forbidden_goods(text, code):
    flags = {flag.code: flag for flag in text_flags(normalize(text))}
    assert flags[code].severity == REJECT


@pytest.mark.parametrize(
    "text",
    [
        "Сим-карта любая, не залочен, не привязан к аккаунту",
        "Без предоплаты, только личная встреча",
        "Не краденый, есть коробка и чек",
        "Камера снимает отлично, есть ночной режим",
        "Зарядка в авто работает",
        "Чехол с котиками в подарок",
    ],
)
def test_ordinary_phrases_raise_nothing(text):
    assert codes(text) == set()


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("Ремонт телефонов любой сложности", "services"),
        ("сдам квартиру на Чуркине", "realty"),
        ("куртка зимняя, 52 размер", "clothes"),
        ("щенки хаски, привиты", "animals"),
        ("продаю оптом, любые модели", "bulk"),
        ("только предоплата на карту", "prepayment"),
        ("карта 2202 2061 2345 6789", "card"),
    ],
)
def test_suspicious_topics_go_to_review(text, code):
    flags = {flag.code: flag for flag in text_flags(normalize(text))}
    assert flags[code].severity == REVIEW


def test_duplicate_of_recent_ad_is_flagged(phones):
    text = "Телефон в отличном состоянии, батарея 90%, есть коробка"
    original = publish(phones, description=text)
    copy = publish(
        phones,
        seller=original.seller,
        description="Телефон в отличном состоянии, батарея 90%, есть коробка и чек",
    )

    flags = [flag for flag in check_rules(copy) if flag.code == "duplicate"]

    assert flags
    assert flags[0].related_ad == original.pk


def test_same_model_from_other_seller_is_not_duplicate(phones):
    publish(phones, description="Телефон в отличном состоянии, батарея 90%, есть коробка")
    other = publish(phones, description="Телефон в отличном состоянии, батарея 90%, есть коробка")

    assert "duplicate" not in {flag.code for flag in check_rules(other)}


def test_symbolic_price_is_rejected(phones):
    ad = publish(phones, price=1)

    flag = next(flag for flag in check_rules(ad) if flag.code == "symbolic_price")

    assert flag.severity == REJECT


def test_price_far_below_market_is_flagged(phones):
    ad = publish(phones, price=12_000)
    PriceStat.objects.create(
        device_model=ad.device_model,
        condition=ad.condition,
        price_key=ad.price_key,
        p25=36_000,
        median=40_000,
        p75=44_000,
        sample_size=8,
    )

    flag = next(flag for flag in check_rules(ad) if flag.code == "low_price")

    assert flag.severity == REVIEW
    assert "3,3 раза ниже рынка" in flag.text


def test_market_with_small_sample_is_ignored(phones):
    ad = publish(phones, price=12_000)
    PriceStat.objects.create(
        device_model=ad.device_model,
        condition=ad.condition,
        price_key=ad.price_key,
        p25=36_000,
        median=40_000,
        p75=44_000,
        sample_size=3,
    )

    assert "low_price" not in {flag.code for flag in check_rules(ad)}
