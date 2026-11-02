import pytest
from django.core.paginator import Paginator
from django.template import Context, Template
from django.test import RequestFactory


def render(source, **context):
    return Template(source).render(Context(context))


def test_price_and_plural_filters():
    assert render("{{ value|price }}", value=12990) == "12 990 ₽"
    assert render("{{ value|price }}", value=None) == ""
    assert render('{{ n|plural:"город,города,городов" }}', n=19) == "городов"
    assert render('{{ n|count_plural:"город,города,городов" }}', n=2) == "2 города"


def test_icon_tag_uses_sprite():
    html = render('{% icon "heart" 16 "is-active" %}')

    assert 'class="icon is-active"' in html
    assert 'width="16"' in html
    assert "sprite.svg#heart" in html


@pytest.mark.parametrize(
    ("number", "expected_href"),
    [(1, '?q=iphone"'), (3, "?q=iphone&amp;page=3")],
)
def test_pagination_keeps_query_params(number, expected_href):
    request = RequestFactory().get("/search/", {"q": "iphone", "page": "2"})
    page = Paginator(range(100), 10).get_page(2)

    html = render("{% pagination page_obj %}", request=request, page_obj=page)

    assert expected_href in html
    assert 'aria-current="page">2<' in html


def test_pagination_hidden_for_single_page():
    request = RequestFactory().get("/")
    page = Paginator(range(5), 10).get_page(1)

    assert render("{% pagination page_obj %}", request=request, page_obj=page).strip() == ""
