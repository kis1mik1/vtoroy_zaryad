from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db.models import Prefetch
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.phone import format_phone
from apps.catalog.models import Category
from apps.catalog.selectors import get_category_tree
from apps.core.decorators import ratelimit
from apps.core.ratelimit import Rate
from apps.core.selectors import get_cities_by_region

from .. import services, session
from ..filters import SearchForm
from ..models import Ad, AdAttributeValue, AdPhoto, AdStatus, SavedSearch
from ..selectors import can_view, card_queryset, similar_ads, sort_queryset, with_market

PAGE_SIZE = 24
PHONE_RATE = Rate(limit=40, period=60 * 60)


def favorite_ids(user) -> set[int]:
    if not user.is_authenticated:
        return set()
    return set(user.favorites.values_list("ad_id", flat=True))


def list_context(request) -> dict:
    return {
        "favorite_ids": favorite_ids(request.user),
        "compare_ids": session.compare_ids(request),
    }


@require_GET
def search(request, category_slug=None):
    category = None
    if category_slug:
        category = get_object_or_404(
            Category.objects.select_related("parent"), slug=category_slug, is_active=True
        )
    form = SearchForm(request.GET, category=category, default_city=request.city)
    form.is_valid()

    queryset = form.filter(card_queryset())
    has_query = bool(form.cleaned_data.get("q", "").strip())
    queryset = sort_queryset(queryset, form.sort_key, relevance=has_query)
    page = Paginator(queryset, PAGE_SIZE).get_page(request.GET.get("page"))

    city = form.city_value()
    query_string = form.query_string()
    saved = (
        request.user.is_authenticated
        and SavedSearch.objects.filter(
            user=request.user, query_string=form.saved_key(request.path)
        ).exists()
    )
    context = {
        "form": form,
        "category": category,
        "page_obj": page,
        "city": city,
        "query": form.cleaned_data.get("q", "").strip(),
        "saved": saved,
        "query_string": query_string,
        "children": list(category.children.filter(is_active=True)) if category else [],
        "tree": get_category_tree() if category is None else [],
        "regions": get_cities_by_region(),
        **list_context(request),
    }
    if category is not None:
        context["breadcrumbs"] = (
            [(category.parent.name, reverse("ads:category", args=[category.parent.slug]))]
            if category.parent_id
            else []
        ) + [(category.name, None)]
    else:
        context["breadcrumbs"] = [("Поиск", None)]

    if request.htmx and not request.htmx.boosted:
        response = render(request, "ads/partials/search_body.html", context)
        page_number = page.number if page.number > 1 else None
        params = "&".join(
            filter(None, [query_string, f"page={page_number}" if page_number else ""])
        )
        response["HX-Push-Url"] = f"{request.path}?{params}" if params else request.path
        return response
    return render(request, "ads/search.html", context)


@require_GET
def ad_detail(request, pk, slug):
    ad = get_object_or_404(
        with_market(Ad.objects.all())
        .select_related("seller__city", "category__parent", "device_model__brand", "brand", "city")
        .prefetch_related(
            Prefetch(
                "photos",
                queryset=AdPhoto.objects.order_by("position", "pk"),
                to_attr="ordered_photos",
            ),
            Prefetch(
                "attribute_values",
                queryset=AdAttributeValue.objects.select_related("attribute", "option").order_by(
                    "attribute__sort_order"
                ),
            ),
            "price_changes",
        ),
        pk=pk,
    )
    if not can_view(ad, request.user):
        raise Http404
    if slug != ad.slug:
        return redirect("ads:detail", pk=ad.pk, slug=ad.slug, permanent=True)

    is_owner = request.user.is_authenticated and request.user.pk == ad.seller_id
    if ad.status == AdStatus.ACTIVE:
        services.register_view(request, ad)
        recent = session.recent_ids(request, exclude=ad.pk)
        session.remember_view(request, ad.pk)
    else:
        recent = session.recent_ids(request, exclude=ad.pk)

    seller = ad.seller
    breadcrumbs = []
    if ad.category.parent_id:
        breadcrumbs.append(
            (ad.category.parent.name, reverse("ads:category", args=[ad.category.parent.slug]))
        )
    breadcrumbs += [
        (ad.category.name, reverse("ads:category", args=[ad.category.slug])),
        (ad.title, None),
    ]

    context = {
        "ad": ad,
        "photos": ad.ordered_photos,
        "report": getattr(ad, "condition_report", None),
        "seller": seller,
        "seller_ads_count": Ad.objects.visible().filter(seller=seller).count(),
        "is_owner": is_owner,
        "similar": similar_ads(ad) if ad.status == AdStatus.ACTIVE else [],
        "recent": recent_ads(recent),
        "breadcrumbs": breadcrumbs,
        **list_context(request),
    }
    return render(request, "ads/ad_detail.html", context)


def recent_ads(ids):
    if not ids:
        return []
    ads = {ad.pk: ad for ad in card_queryset().filter(pk__in=ids)}
    return [ads[pk] for pk in ids if pk in ads][:6]


@require_POST
@ratelimit("phone", PHONE_RATE, key="user")
def ad_phone(request, pk):
    if not request.user.is_authenticated:
        login_url = f"{reverse('accounts:login')}?next={request.POST.get('next', '/')}"
        if request.htmx:
            response = render(request, "ads/partials/phone.html", {"login_url": login_url})
            response["HX-Redirect"] = login_url
            return response
        return redirect(login_url)
    ad = get_object_or_404(Ad.objects.visible().select_related("seller"), pk=pk)
    seller = ad.seller
    phone = format_phone(seller.phone) if seller.shows_phone else ""
    if phone and request.user.pk != seller.pk:
        services.register_phone_reveal(ad)
    return render(request, "ads/partials/phone.html", {"phone": phone, "ad": ad})


@require_GET
def user_profile(request, pk):
    user_model = get_user_model()
    seller = get_object_or_404(
        user_model.objects.select_related("city"), pk=pk, is_active=True, deleted_at__isnull=True
    )
    if seller.is_banned and not request.user.is_staff:
        raise Http404
    ads = card_queryset(Ad.objects.visible().filter(seller=seller)).order_by(
        "-is_pinned", "-bumped_at"
    )
    page = Paginator(ads, PAGE_SIZE).get_page(request.GET.get("page"))
    return render(
        request,
        "ads/profile.html",
        {
            "seller": seller,
            "page_obj": page,
            "sold_count": Ad.objects.alive().filter(seller=seller, status=AdStatus.SOLD).count(),
            "breadcrumbs": [(seller.first_name, None)],
            **list_context(request),
        },
    )


HOME_FRESH_LIMIT = 12


@require_GET
def home(request):
    fresh = Ad.objects.visible()
    if request.city is not None:
        fresh = fresh.filter(city=request.city)
    return render(
        request,
        "core/home.html",
        {
            "tree": get_category_tree(),
            "fresh": list(sort_queryset(card_queryset(fresh), "date")[:HOME_FRESH_LIMIT]),
            "recent": recent_ads(session.recent_ids(request)),
            **list_context(request),
        },
    )
