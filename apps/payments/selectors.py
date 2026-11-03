from django.db.models import Prefetch

from apps.ads.models import AdPhoto

from .models import Payment, PromotionTariff


def active_tariffs():
    return PromotionTariff.objects.filter(is_active=True)


def user_payments(user):
    return (
        Payment.objects.filter(user=user)
        .select_related("ad", "tariff")
        .prefetch_related(
            Prefetch(
                "ad__photos",
                queryset=AdPhoto.objects.order_by("position", "pk"),
                to_attr="ordered_photos",
            )
        )
    )


def ad_payments(ad, limit: int = 5) -> list[Payment]:
    return list(Payment.objects.filter(ad=ad).select_related("tariff")[:limit])
