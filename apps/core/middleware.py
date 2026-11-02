from django.contrib.messages import get_messages
from django.template.loader import render_to_string

from .selectors import get_city_by_slug, get_default_city

CITY_SESSION_KEY = "city"
ALL_CITIES = "all"


def resolve_city(request):
    slug = request.session.get(CITY_SESSION_KEY)
    if slug == ALL_CITIES:
        return None
    if slug:
        city = get_city_by_slug(slug)
        if city is not None:
            return city
    user_city = getattr(request.user, "city", None) if request.user.is_authenticated else None
    return user_city or get_default_city()


class CurrentCityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.city = resolve_city(request)
        return self.get_response(request)


class HtmxMessagesMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if not getattr(request, "htmx", False) or request.htmx.boosted:
            return response
        if response.streaming or "text/html" not in response.get("Content-Type", ""):
            return response
        if 300 <= response.status_code < 400 or "HX-Redirect" in response:
            return response

        storage = get_messages(request)
        if not storage:
            return response
        response.write(
            render_to_string("components/toasts.html", {"messages": storage, "oob": True})
        )
        return response
