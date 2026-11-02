from urllib.parse import urlsplit

from django.http import QueryDict
from django.utils import timezone

from apps.catalog.models import Category
from apps.notifications.models import NotificationKind
from apps.notifications.services import notify

from .filters import SearchForm
from .models import Ad, SavedSearch
from .selectors import card_queryset


def matching_ads(search: SavedSearch, since):
    parts = urlsplit(search.query_string)
    category = None
    if parts.path.startswith("/c/"):
        category = Category.objects.filter(slug=parts.path.strip("/").split("/")[-1]).first()
        if category is None:
            return Ad.objects.none()
    form = SearchForm(QueryDict(parts.query), category=category, default_city=None)
    form.is_valid()
    return form.filter(card_queryset(Ad.objects.visible().filter(published_at__gt=since)))


def check_saved_searches() -> int:
    notified = 0
    now = timezone.now()
    for search in SavedSearch.objects.filter(notify=True).select_related("user"):
        if not search.user.is_active:
            continue
        count = matching_ads(search, search.last_checked_at).count()
        if count:
            notify(
                search.user,
                NotificationKind.SAVED_SEARCH,
                f"Новые объявления: {search.name}",
                f"Нашлось новых объявлений: {count}.",
                url=search.query_string,
            )
            notified += 1
        search.last_checked_at = now
        search.save(update_fields=["last_checked_at"])
    return notified
