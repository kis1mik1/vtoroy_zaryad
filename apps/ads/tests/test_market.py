import pytest
from django.urls import reverse

from apps.ads.market import PercentileCont, price_hint, recalculate_price_stats
from apps.ads.models import Ad, PriceStat
from apps.ads.selectors import card_queryset, market_label

from .helpers import publish

pytestmark = pytest.mark.django_db


@pytest.fixture
def market(phones):
    phones["attributes"]["storage"].is_price_key = True
    phones["attributes"]["storage"].save()
    ads = [publish(phones, price=price) for price in (30_000, 35_000, 40_000, 45_000, 50_000)]
    recalculate_price_stats()
    return ads


def test_percentiles(market, phones):
    stat = PriceStat.objects.get()

    assert (stat.p25, stat.median, stat.p75, stat.sample_size) == (35_000, 40_000, 45_000, 5)
    assert stat.key_option == phones["storage"]["128 ГБ"]


def test_market_labels(market):
    labels = {ad.price: market_label(ad) for ad in card_queryset()}

    assert labels[30_000].text == "Ниже рынка"
    assert labels[40_000].text == "В рынке"
    assert labels[50_000].text == "Выше рынка"


def test_no_label_for_small_sample(phones):
    phones["attributes"]["storage"].is_price_key = True
    phones["attributes"]["storage"].save()
    for price in (30_000, 40_000):
        publish(phones, price=price)
    recalculate_price_stats()

    assert all(market_label(ad) is None for ad in card_queryset())


def test_stats_separate_by_storage(market, phones):
    publish(phones, storage="256 ГБ", price=60_000)
    recalculate_price_stats()

    assert PriceStat.objects.count() == 2
    big = card_queryset().get(price=60_000)
    assert market_label(big) is None


def test_sort_below_market_first(market):
    from apps.ads.selectors import sort_queryset

    prices = [ad.price for ad in sort_queryset(card_queryset(), "market")]

    assert prices == sorted(prices)


def test_price_hint_and_form_section(auth_client, market, phones):
    hint = price_hint(phones["iphone"], "used", phones["storage"]["128 ГБ"].pk)
    assert hint.median == 40_000

    response = auth_client.get(
        reverse("ads:form_section"),
        {
            "category": phones["category"].pk,
            "brand": phones["apple"].pk,
            "device_model": phones["iphone"].pk,
            "attr_storage": phones["storage"]["128 ГБ"].pk,
            "condition": "used",
        },
    )
    assert "Рыночная цена" in response.content.decode()


def test_stale_stats_removed(market):
    Ad.objects.update(is_deleted=True)

    recalculate_price_stats()

    assert not PriceStat.objects.exists()


def test_percentile_validation():
    with pytest.raises(ValueError, match="Перцентиль"):
        PercentileCont("price", 1.5)
