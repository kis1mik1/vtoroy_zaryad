from datetime import timedelta

import pytest
from django.http import QueryDict
from django.urls import reverse
from django.utils import timezone

from apps.ads.filters import SearchForm
from apps.ads.models import Ad
from apps.ads.search import apply_query
from apps.ads.selectors import card_queryset, sort_queryset
from apps.core.models import City

from .helpers import publish

pytestmark = pytest.mark.django_db


def search(phones, query="", category=None, city=None):
    form = SearchForm(QueryDict(query), category=category, default_city=city)
    form.is_valid()
    return form, form.filter(card_queryset())


def test_index_contains_aliases_and_price_key(phones):
    phones["iphone"].aliases = ["айфон 13"]
    phones["iphone"].save()
    phones["attributes"]["storage"].is_price_key = True
    phones["attributes"]["storage"].save()

    ad = publish(phones, storage="256 ГБ")

    assert "айфон 13" in ad.search_text
    assert ad.price_key == phones["storage"]["256 ГБ"].pk
    assert ad.search_vector is not None


@pytest.mark.parametrize("query", ["iphone 13", "айфон 13", "айфн 13", "APPLE"])
def test_query_finds_ad_by_alias_and_typo(phones, query):
    phones["iphone"].aliases = ["айфон 13"]
    phones["iphone"].save()
    ad = publish(phones)

    assert list(apply_query(Ad.objects.visible(), query)) == [ad]


def test_query_without_matches(phones):
    publish(phones)

    assert not apply_query(Ad.objects.visible(), "видеокарта").exists()


def test_city_defaults_to_current_and_all_overrides(phones):
    vladivostok = City.objects.get(slug="vladivostok")
    here = publish(phones, city="vladivostok")
    there = publish(phones, city="khabarovsk")

    _, local = search(phones, city=vladivostok)
    _, everywhere = search(phones, "city=all", city=vladivostok)

    assert list(local) == [here]
    assert set(everywhere) == {here, there}


def test_price_condition_and_brand_filters(phones):
    cheap = publish(phones, price=20_000)
    new = publish(phones, price=60_000, condition="new")

    assert list(search(phones, "price_max=30000")[1]) == [cheap]
    assert list(search(phones, "condition=new")[1]) == [new]
    assert set(search(phones, "brand=apple-test")[1]) == {cheap, new}
    assert set(search(phones, "brand=unknown")[1]) == {cheap, new}


def test_attribute_filters_in_leaf_category(phones):
    phones["attributes"]["storage"].is_filterable = True
    phones["attributes"]["storage"].save()
    phones["attributes"]["screen"].is_filterable = True
    phones["attributes"]["screen"].save()
    small = publish(phones, storage="128 ГБ")
    big = publish(phones, storage="256 ГБ")
    option = phones["storage"]["256 ГБ"].pk

    form, found = search(phones, f"a_storage={option}", category=phones["category"])
    assert [field for _, field in form.attribute_fields]
    assert list(found) == [big]

    _, by_screen = search(phones, "a_screen_min=6&a_screen_max=6,2", category=phones["category"])
    assert set(by_screen) == {small, big}
    _, none = search(phones, "a_screen_min=7", category=phones["category"])
    assert not none.exists()


def test_parent_category_includes_children(phones):
    ad = publish(phones)

    _, found = search(phones, category=phones["category"].parent)

    assert list(found) == [ad]


def test_sorting_pins_first_and_prices(phones):
    first = publish(phones, price=30_000)
    second = publish(phones, price=10_000)
    Ad.objects.filter(pk=first.pk).update(pinned_until=timezone.now() + timedelta(days=1))

    by_date = list(sort_queryset(card_queryset(), "date"))
    by_price = list(sort_queryset(card_queryset(), "price_asc"))

    assert by_date[0] == first
    assert by_price == [second, first]


def test_canonical_params_and_saved_key(phones):
    vladivostok = City.objects.get(slug="vladivostok")
    form = SearchForm(
        QueryDict("q=+iphone+&price_max=50000&sort=date&page=3&brand=b&brand=a"),
        category=None,
        default_city=vladivostok,
    )
    form.fields["brand"].choices = [("a", "A"), ("b", "B")]
    form.is_valid()

    assert form.query_string() == "brand=a&brand=b&price_max=50000&q=iphone"
    assert (
        form.saved_key("/search/")
        == "/search/?brand=a&brand=b&city=vladivostok&price_max=50000&q=iphone"
    )
    assert "до 50 000 ₽" in form.describe()
    assert form.active_filters_count() == 2


def test_search_page_and_htmx_partial(client, phones):
    ad = publish(phones)

    page = client.get(reverse("ads:search"), {"q": "iphone", "city": "all"})
    partial = client.get(
        reverse("ads:search"),
        {"q": "iphone", "city": "all", "price_min": ""},
        headers={"HX-Request": "true"},
    )

    assert ad.title in page.content.decode()
    assert "1 объявление" in page.content.decode()
    assert "<html" not in partial.content.decode()
    assert partial["HX-Push-Url"] == "/search/?city=all&q=iphone"


def test_category_page_with_bad_params(client, phones):
    response = client.get(
        reverse("ads:category", args=[phones["category"].slug]),
        {"price_min": "abc", "a_storage": "x", "sort": "unknown"},
    )

    assert response.status_code == 200
    assert "Смартфоны" in response.content.decode()


def test_unknown_category_404(client):
    assert client.get(reverse("ads:category", args=["no-such"])).status_code == 404


def test_empty_results_suggest_all_cities(client, phones):
    response = client.get(reverse("ads:search"), {"q": "видеокарта"})

    html = response.content.decode()
    assert "По вашему запросу пока ничего нет" in html
    assert "city=all" in html
