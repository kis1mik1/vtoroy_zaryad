from django import template
from django.conf import settings
from django.templatetags.static import static
from django.utils.html import format_html

from apps.core import captcha as smartcaptcha
from apps.core import text

register = template.Library()


@register.filter
def price(value):
    if value in (None, ""):
        return ""
    return text.format_price(value)


@register.filter
def number(value):
    if value in (None, ""):
        return ""
    return text.format_number(value)


@register.filter
def plural(value, forms):
    return text.plural_form(value, forms.split(","))


@register.filter
def count_plural(value, forms):
    return f"{text.format_number(value)}{text.NBSP}{text.plural_form(value, forms.split(','))}"


@register.filter
def humandate(value):
    if not value:
        return ""
    return text.human_datetime(value)


@register.filter
def day(value):
    if not value:
        return ""
    return text.format_day(value)


@register.simple_tag
def icon(name, size=20, css_class=""):
    classes = f"icon {css_class}".strip()
    return format_html(
        '<svg class="{}" width="{}" height="{}" aria-hidden="true" focusable="false">'
        '<use href="{}#{}"></use></svg>',
        classes,
        size,
        size,
        static("icons/sprite.svg"),
        name,
    )


@register.inclusion_tag("components/pagination.html", takes_context=True)
def pagination(context, page_obj, param="page"):
    page_range = page_obj.paginator.get_elided_page_range(
        page_obj.number, on_each_side=1, on_ends=1
    )
    return {
        "request": context["request"],
        "page_obj": page_obj,
        "page_range": page_range,
        "param": param,
        "ellipsis": page_obj.paginator.ELLIPSIS,
    }


@register.simple_tag(takes_context=True)
def page_url(context, number, param="page"):
    query = context["request"].GET.copy()
    if number == 1:
        query.pop(param, None)
    else:
        query[param] = number
    encoded = query.urlencode()
    return f"?{encoded}" if encoded else context["request"].path


@register.inclusion_tag("components/forms/captcha.html")
def captcha():
    return {
        "test_mode": smartcaptcha.is_test_mode(),
        "site_key": settings.SMARTCAPTCHA_CLIENT_KEY,
        "script_url": smartcaptcha.SCRIPT_URL,
        "token_field": smartcaptcha.TOKEN_FIELD,
        "test_token": smartcaptcha.TEST_TOKEN,
    }
