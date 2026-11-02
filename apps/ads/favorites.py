from django.db import IntegrityError, transaction
from django.db.models import F
from django.urls import reverse

from apps.core.text import format_price
from apps.notifications.models import NotificationKind
from apps.notifications.services import notify

from .models import Ad, Favorite


@transaction.atomic
def toggle(user, ad: Ad) -> bool:
    deleted, _ = Favorite.objects.filter(user=user, ad=ad).delete()
    if deleted:
        Ad.objects.filter(pk=ad.pk).update(favorites_count=F("favorites_count") - 1)
        return False
    try:
        with transaction.atomic():
            Favorite.objects.create(user=user, ad=ad)
    except IntegrityError:
        return True
    Ad.objects.filter(pk=ad.pk).update(favorites_count=F("favorites_count") + 1)
    return True


def notify_price_drop(ad: Ad, old_price: int, new_price: int) -> int:
    url = reverse("ads:detail", args=[ad.pk, ad.slug])
    count = 0
    for favorite in Favorite.objects.filter(ad=ad).exclude(user=ad.seller).select_related("user"):
        notify(
            favorite.user,
            NotificationKind.PRICE_DROP,
            f"Цена снизилась: {ad.title}",
            f"Было {format_price(old_price)}, стало {format_price(new_price)}.",
            url=url,
        )
        count += 1
    return count
