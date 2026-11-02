import pytest
from django.urls import reverse

from apps.core.middleware import ALL_CITIES, CITY_SESSION_KEY
from apps.core.models import City
from apps.core.selectors import get_cities, get_cities_by_region, get_default_city

from .factories import CityFactory

pytestmark = pytest.mark.django_db


def test_data_migration_loads_far_east_cities():
    assert City.objects.count() == 19
    assert City.objects.get(is_default=True).slug == "vladivostok"
    assert City.objects.filter(region="Приморский край").count() == 11
    assert City.objects.first().name == "Владивосток"


def test_cities_grouped_by_region_in_order():
    regions = [region for region, _ in get_cities_by_region()]

    assert regions[0] == "Приморский край"
    assert regions[1] == "Хабаровский край"
    assert len(regions) == len(set(regions))


def test_only_one_default_city_allowed():
    with pytest.raises(Exception, match="city_single_default"):
        CityFactory(is_default=True)


def test_cities_cache_is_reset_on_save():
    assert len(get_cities()) == 19
    CityFactory(name="Анадырь", slug="anadyr", region="Чукотский автономный округ")

    assert len(get_cities()) == 20


def test_default_city_shown_in_header(client):
    response = client.get(reverse("core:home"))

    assert response.context["current_city"] == get_default_city()
    assert "Владивосток" in response.content.decode()


def test_select_city_saves_to_session_and_redirects_back(client):
    response = client.post(reverse("core:city_select"), {"city": "khabarovsk", "next": "/rules/"})

    assert response.status_code == 302
    assert response.url == "/rules/"
    assert client.session[CITY_SESSION_KEY] == "khabarovsk"
    assert client.get("/rules/").context["current_city"].slug == "khabarovsk"


def test_select_all_cities(client):
    client.post(reverse("core:city_select"), {"city": ALL_CITIES})

    response = client.get(reverse("core:home"))

    assert response.context["current_city"] is None
    assert "Все города" in response.content.decode()


def test_select_city_ignores_external_next(client):
    response = client.post(
        reverse("core:city_select"), {"city": "nakhodka", "next": "https://evil.example/"}
    )

    assert response.url == "/"


def test_select_unknown_city_shows_error(client):
    response = client.post(reverse("core:city_select"), {"city": "moscow"}, follow=True)

    assert CITY_SESSION_KEY not in client.session
    assert "Такого города нет в списке" in response.content.decode()


def test_stale_city_in_session_falls_back_to_default(client):
    session = client.session
    session[CITY_SESSION_KEY] = "removed-city"
    session.save()

    response = client.get(reverse("core:home"))

    assert response.context["current_city"].slug == "vladivostok"


def test_city_picker_returns_partial_for_htmx(client):
    response = client.get(reverse("core:city_select"), headers={"HX-Request": "true"})
    html = response.content.decode()

    assert response.status_code == 200
    assert "<html" not in html
    assert "Хабаровский край" in html


def test_city_picker_full_page_without_htmx(client):
    response = client.get(reverse("core:city_select"))

    assert "<html" in response.content.decode()
