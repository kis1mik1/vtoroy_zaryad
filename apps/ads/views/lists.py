import json
from urllib.parse import urlsplit

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Prefetch
from django.http import HttpResponse, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from apps.catalog.models import Category
from apps.core.decorators import ratelimit
from apps.core.ratelimit import Rate

from .. import favorites, session
from ..filters import SearchForm
from ..models import Ad, AdAttributeValue, SavedSearch, SurfaceState
from ..selectors import card_queryset
from .browse import PAGE_SIZE, list_context

SAVED_SEARCH_LIMIT = 30
FAVORITE_RATE = Rate(limit=120, period=60 * 60)


def _toast(response, text, level="success"):
    response["HX-Trigger"] = json.dumps({"toast": {"level": level, "text": text}})
    return response


def _back(request, fallback):
    target = request.POST.get("next") or request.META.get("HTTP_REFERER", "")
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        return redirect(target)
    return redirect(fallback)


@require_POST
@ratelimit("favorite", FAVORITE_RATE, key="user")
def favorite_toggle(request, pk):
    if not request.user.is_authenticated:
        login_url = f"{reverse('accounts:login')}?next={request.POST.get('next', '/')}"
        if request.htmx:
            response = HttpResponse(status=204)
            response["HX-Redirect"] = login_url
            return response
        return redirect(login_url)
    ad = get_object_or_404(Ad.objects.alive(), pk=pk)
    added = favorites.toggle(request.user, ad)
    if request.htmx:
        response = render(
            request,
            "ads/partials/favorite_button.html",
            {"ad": ad, "is_favorite": added, "variant": request.POST.get("variant", "icon")},
        )
        return _toast(response, "Добавлено в избранное" if added else "Убрано из избранного")
    messages.success(request, "Добавлено в избранное" if added else "Убрано из избранного")
    return _back(request, reverse("ads:favorites"))


@login_required
@require_GET
def my_favorites(request):
    ads = card_queryset(Ad.objects.alive().filter(favorites__user=request.user)).order_by(
        "-favorites__created_at"
    )
    page = Paginator(ads, PAGE_SIZE).get_page(request.GET.get("page"))
    return render(
        request,
        "ads/favorites.html",
        {"page_obj": page, "breadcrumbs": [("Избранное", None)], **list_context(request)},
    )


@require_POST
def compare_toggle(request, pk):
    ad = get_object_or_404(Ad.objects.visible(), pk=pk)
    try:
        added = session.toggle_compare(request, ad.pk)
    except session.CompareFull:
        message = f"Сравнивать можно до {session.COMPARE_LIMIT} объявлений. Уберите одно из списка."
        if request.htmx:
            return _toast(HttpResponse(status=204), message, "warning")
        messages.warning(request, message)
        return _back(request, reverse("ads:compare"))
    text = "Добавлено к сравнению" if added else "Убрано из сравнения"
    if request.htmx:
        response = render(
            request,
            "ads/partials/compare_button.html",
            {"ad": ad, "in_compare": added, "variant": request.POST.get("variant", "icon")},
        )
        response.write(
            render(request, "ads/partials/compare_bar.html", {"oob": True}).content.decode()
        )
        return _toast(response, text)
    messages.success(request, text)
    return _back(request, reverse("ads:compare"))


@require_GET
def compare(request):
    ids = session.compare_ids(request)
    ads_by_id = {
        ad.pk: ad
        for ad in card_queryset(Ad.objects.visible().filter(pk__in=ids)).prefetch_related(
            Prefetch(
                "attribute_values",
                queryset=AdAttributeValue.objects.select_related("attribute", "option"),
            ),
            "condition_report",
        )
    }
    ads = [ads_by_id[pk] for pk in ids if pk in ads_by_id]
    if len(ads) != len(ids):
        session.set_compare(request, [ad.pk for ad in ads])
    return render(
        request,
        "ads/compare.html",
        {"ads": ads, "rows": _compare_rows(ads), "breadcrumbs": [("Сравнение", None)]},
    )


def _compare_rows(ads):
    if not ads:
        return []
    rows = []
    attributes = {}
    for ad in ads:
        for value in ad.attribute_values.all():
            attributes.setdefault(value.attribute.name, (value.attribute.sort_order, {}))[1][
                ad.pk
            ] = value.display
    for name, (_, values) in sorted(attributes.items(), key=lambda item: item[1][0]):
        cells = [values.get(ad.pk, "—") for ad in ads]
        rows.append((name, cells, len(set(cells)) > 1))

    def report(ad, attr, labels=None):
        item = getattr(ad, "condition_report", None)
        value = getattr(item, attr, None) if item else None
        if value in (None, ""):
            return "—"
        if labels:
            return labels.get(value, value)
        return value

    surface = dict(SurfaceState.choices)
    extra = [
        ("Состояние", [ad.get_condition_display() for ad in ads]),
        ("Экран", [report(ad, "screen_state", surface) for ad in ads]),
        ("Корпус", [report(ad, "body_state", surface) for ad in ads]),
        (
            "Аккумулятор",
            [f"{v}%" if (v := report(ad, "battery_health")) != "—" else v for ad in ads],
        ),
        ("Город", [ad.city.name for ad in ads]),
    ]
    for name, cells in extra:
        if any(cell != "—" for cell in cells):
            rows.append((name, cells, len(set(cells)) > 1))
    return rows


@require_POST
def compare_clear(request):
    session.set_compare(request, [])
    messages.success(request, "Список сравнения очищен")
    return redirect("ads:compare")


@login_required
@require_POST
def saved_search_create(request):
    target = request.POST.get("url", "")
    parts = urlsplit(target)
    if parts.netloc or not (parts.path == reverse("ads:search") or parts.path.startswith("/c/")):
        return _toast(HttpResponse(status=400), "Не удалось сохранить поиск.", "error")
    category = None
    if parts.path.startswith("/c/"):
        category = Category.objects.filter(slug=parts.path.strip("/").split("/")[-1]).first()
    form = SearchForm(QueryDict(parts.query), category=category, default_city=request.city)
    form.is_valid()
    key = form.saved_key(parts.path)
    if request.user.saved_searches.count() >= SAVED_SEARCH_LIMIT:
        message = f"Можно сохранить до {SAVED_SEARCH_LIMIT} поисков. Удалите ненужные."
        return _toast(HttpResponse(status=204), message, "warning")
    SavedSearch.objects.get_or_create(
        user=request.user, query_string=key, defaults={"name": form.describe()}
    )
    response = render(request, "ads/partials/saved_button.html", {"saved": True})
    return _toast(response, "Поиск сохранён. Пришлём уведомление о новых объявлениях.")


@login_required
@require_GET
def my_searches(request):
    return render(
        request,
        "ads/saved_searches.html",
        {
            "searches": request.user.saved_searches.all(),
            "breadcrumbs": [("Сохранённые поиски", None)],
        },
    )


@login_required
@require_POST
def saved_search_update(request, pk, action):
    search = get_object_or_404(SavedSearch, pk=pk, user=request.user)
    if action == "delete":
        search.delete()
        messages.success(request, "Поиск удалён")
    elif action == "notify":
        search.notify = not search.notify
        search.save(update_fields=["notify"])
        messages.success(
            request, "Уведомления включены" if search.notify else "Уведомления выключены"
        )
    return redirect("ads:saved_searches")
