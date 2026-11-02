from django.contrib import messages
from django.core.cache import cache
from django.db import connection
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods
from django.views.generic import TemplateView

from .middleware import ALL_CITIES, CITY_SESSION_KEY
from .selectors import get_cities_by_region, get_city_by_slug
from .styleguide import DemoForm, demo_page, sample_dates

INFO_PAGES = (
    ("core:rules", "Правила размещения"),
    ("core:safety", "Безопасная сделка"),
    ("core:terms", "Пользовательское соглашение"),
    ("core:privacy", "Политика конфиденциальности"),
    ("core:about", "О проекте"),
)


class InfoPageView(TemplateView):
    title = ""
    description = ""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            title=self.title,
            description=self.description,
            info_pages=[(reverse(name), label) for name, label in INFO_PAGES],
            breadcrumbs=[(self.title, None)],
        )
        return context


def _safe_next(request, fallback="/"):
    candidate = request.POST.get("next") or request.GET.get("next")
    if candidate and url_has_allowed_host_and_scheme(
        candidate, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return candidate
    return fallback


@require_http_methods(["GET", "POST"])
def city_select(request):
    if request.method == "POST":
        slug = request.POST.get("city", "")
        if slug == ALL_CITIES:
            request.session[CITY_SESSION_KEY] = ALL_CITIES
            messages.success(request, "Показываем объявления всех городов")
        else:
            city = get_city_by_slug(slug)
            if city is None:
                messages.error(request, "Такого города нет в списке")
                return HttpResponseRedirect(reverse("core:city_select"))
            request.session[CITY_SESSION_KEY] = city.slug
            messages.success(request, f"Город: {city.name}")
        return HttpResponseRedirect(_safe_next(request))

    template = "core/partials/city_picker.html" if request.htmx else "core/city_select.html"
    return render(
        request,
        template,
        {
            "regions": get_cities_by_region(),
            "next": _safe_next(request, fallback=""),
            "all_cities": ALL_CITIES,
            "breadcrumbs": [("Выбор города", None)],
        },
    )


@require_GET
def robots_txt(request):
    return render(request, "robots.txt", content_type="text/plain; charset=utf-8")


@never_cache
@require_GET
def health(request):
    checks = {}
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "error"
    try:
        cache.set("health:ping", "1", 5)
        checks["cache"] = "ok" if cache.get("health:ping") == "1" else "error"
    except Exception:
        checks["cache"] = "error"

    healthy = all(value == "ok" for value in checks.values())
    return JsonResponse(
        {"status": "ok" if healthy else "error", **checks}, status=200 if healthy else 503
    )


def csrf_failure(request, reason=""):
    return render(request, "errors/403_csrf.html", status=403)


def bad_request(request, exception=None):
    return render(request, "errors/400.html", status=400)


def permission_denied(request, exception=None):
    return render(request, "errors/403.html", status=403)


def page_not_found(request, exception=None):
    return render(request, "errors/404.html", status=404)


def server_error(request):
    return render(request, "errors/500.html", status=500)


def styleguide(request):
    form = DemoForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        messages.success(request, "Форма прошла проверку")
        return HttpResponseRedirect(request.path)
    if request.GET.get("toast"):
        level = request.GET["toast"]
        getattr(messages, level, messages.info)(request, f"Пример уведомления: {level}")
        if request.htmx:
            return render(request, "dev/partials/toast_ok.html")
    return render(
        request,
        "dev/styleguide.html",
        {"form": form, "page_obj": demo_page(request), "sample_dates": sample_dates()},
    )
