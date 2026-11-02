from dataclasses import dataclass, field
from datetime import timedelta

from django.core.cache import cache
from django.db import transaction
from django.db.models import F
from django.urls import reverse
from django.utils import timezone

from apps.catalog.models import Attribute
from apps.core.text import slugify_ru
from apps.notifications.models import NotificationKind
from apps.notifications.services import notify

from .models import Ad, AdAttributeValue, AdStatus, ConditionReport, PriceChange
from .photos import attach_photos
from .search import index_ad
from .tasks import notify_price_drop_task

ARCHIVE_AFTER = timedelta(days=30)
MODERATED_FIELDS = (
    "category_id",
    "device_model_id",
    "brand_id",
    "custom_model_name",
    "title",
    "description",
)


class TransitionError(Exception):
    pass


@dataclass
class AttributeValue:
    attribute: Attribute
    option: object = None
    number: object = None
    flag: bool | None = None

    @property
    def display(self) -> str:
        if self.option is not None:
            return self.option.value
        if self.number is not None:
            return self.attribute.format_number(self.number)
        if self.flag is not None:
            return "есть" if self.flag else "нет"
        return ""


@dataclass
class AdDraft:
    fields: dict
    attributes: list[AttributeValue] = field(default_factory=list)
    condition: dict = field(default_factory=dict)
    photos: list = field(default_factory=list)


def build_title(*, device_model=None, brand=None, custom_name="", attributes=()) -> str:
    if device_model is not None:
        base = device_model.full_name
    else:
        base = " ".join(filter(None, [brand.name if brand else "", custom_name.strip()]))
    base_words = set(base.lower().split())
    parts = [base]
    for value in sorted(attributes, key=lambda v: v.attribute.sort_order):
        display = value.display
        if not value.attribute.in_title or not display:
            continue
        if set(display.lower().split()) <= base_words:
            continue
        parts.append(display)
    title = ", ".join(part for part in parts if part)
    return title[:120]


def _ad_url(ad) -> str:
    return f"{reverse('ads:my_ads')}?status={ad.status}"


def _apply_attributes(ad: Ad, values: list[AttributeValue]) -> None:
    ad.attribute_values.all().delete()
    AdAttributeValue.objects.bulk_create(
        AdAttributeValue(
            ad=ad,
            attribute=value.attribute,
            option=value.option,
            value_number=value.number,
            value_bool=value.flag,
        )
        for value in values
        if value.option is not None or value.number is not None or value.flag is not None
    )


def _apply_condition(ad: Ad, data: dict) -> None:
    ConditionReport.objects.update_or_create(ad=ad, defaults=data)


@transaction.atomic
def create_ad(seller, draft: AdDraft) -> Ad:
    ad = Ad(seller=seller, **draft.fields)
    if not ad.title:
        ad.title = build_title(
            device_model=ad.device_model,
            brand=ad.brand,
            custom_name=ad.custom_model_name,
            attributes=draft.attributes,
        )
    ad.slug = slugify_ru(ad.title) or "ad"
    ad.status = AdStatus.PENDING
    ad.status_changed_at = timezone.now()
    ad.save()
    _apply_attributes(ad, draft.attributes)
    _apply_condition(ad, draft.condition)
    attach_photos(ad, draft.photos)
    index_ad(ad)
    return ad


@transaction.atomic
def update_ad(ad: Ad, draft: AdDraft) -> bool:
    ad = Ad.objects.select_for_update().get(pk=ad.pk)
    if not ad.is_editable:
        raise TransitionError("Проданное объявление нельзя изменить.")
    before = {name: getattr(ad, name) for name in MODERATED_FIELDS}
    old_price = ad.price

    for name, value in draft.fields.items():
        setattr(ad, name, value)
    if not ad.title:
        ad.title = build_title(
            device_model=ad.device_model,
            brand=ad.brand,
            custom_name=ad.custom_model_name,
            attributes=draft.attributes,
        )
    ad.slug = slugify_ru(ad.title) or "ad"

    photos_changed = attach_photos(ad, draft.photos)
    moderated_changed = photos_changed or any(
        getattr(ad, name) != value for name, value in before.items()
    )
    needs_review = moderated_changed and ad.status in (AdStatus.ACTIVE, AdStatus.REJECTED)
    if needs_review or ad.status == AdStatus.REJECTED:
        ad.status = AdStatus.PENDING
        ad.status_changed_at = timezone.now()
        ad.rejection_reason = ""
    ad.save()

    if ad.price != old_price:
        PriceChange.objects.create(ad=ad, old_price=old_price, new_price=ad.price)
        if ad.price < old_price and ad.status == AdStatus.ACTIVE:
            transaction.on_commit(lambda: notify_price_drop_task.delay(ad.pk, old_price, ad.price))
    _apply_attributes(ad, draft.attributes)
    _apply_condition(ad, draft.condition)
    index_ad(ad)
    return ad.status == AdStatus.PENDING


def _set_status(ad: Ad, status: str, **extra) -> None:
    ad.status = status
    ad.status_changed_at = timezone.now()
    for name, value in extra.items():
        setattr(ad, name, value)
    ad.save(update_fields=["status", "status_changed_at", "updated_at", *extra])


@transaction.atomic
def approve(ad: Ad, moderator=None) -> None:
    ad = Ad.objects.select_for_update().get(pk=ad.pk)
    if ad.status != AdStatus.PENDING:
        raise TransitionError("Одобрить можно только объявление на проверке.")
    now = timezone.now()
    _set_status(
        ad,
        AdStatus.ACTIVE,
        rejection_reason="",
        published_at=ad.published_at or now,
        bumped_at=ad.bumped_at or now,
    )
    notify(
        ad.seller,
        NotificationKind.MODERATION,
        f"Объявление опубликовано: {ad.title}",
        "Его уже видят покупатели.",
        url=_ad_url(ad),
    )


@transaction.atomic
def reject(ad: Ad, reason: str, moderator=None) -> None:
    ad = Ad.objects.select_for_update().get(pk=ad.pk)
    if ad.status not in (AdStatus.PENDING, AdStatus.ACTIVE):
        raise TransitionError("Отклонить можно только объявление на проверке или активное.")
    _set_status(ad, AdStatus.REJECTED, rejection_reason=reason)
    notify(
        ad.seller,
        NotificationKind.MODERATION,
        f"Объявление отклонено: {ad.title}",
        f"Причина: {reason}\nИсправьте объявление и отправьте его на проверку снова.",
        url=_ad_url(ad),
    )


@transaction.atomic
def withdraw(ad: Ad) -> None:
    if ad.status not in (AdStatus.ACTIVE, AdStatus.PENDING):
        raise TransitionError("Снять с публикации можно только активное объявление.")
    _set_status(ad, AdStatus.ARCHIVED)


@transaction.atomic
def mark_sold(ad: Ad) -> None:
    if ad.status not in (AdStatus.ACTIVE, AdStatus.ARCHIVED):
        raise TransitionError("Отметить проданным можно активное объявление или из архива.")
    _set_status(ad, AdStatus.SOLD)


@transaction.atomic
def restore(ad: Ad) -> None:
    if ad.status != AdStatus.ARCHIVED:
        raise TransitionError("Вернуть можно только объявление из архива.")
    if ad.published_at is None:
        _set_status(ad, AdStatus.PENDING)
    else:
        _set_status(ad, AdStatus.ACTIVE, bumped_at=timezone.now())


@transaction.atomic
def delete(ad: Ad) -> None:
    if ad.status in (AdStatus.ACTIVE, AdStatus.PENDING):
        raise TransitionError("Сначала снимите объявление с публикации.")
    ad.is_deleted = True
    ad.save(update_fields=["is_deleted", "updated_at"])


def archive_stale() -> int:
    threshold = timezone.now() - ARCHIVE_AFTER
    return (
        Ad.objects.alive()
        .filter(status=AdStatus.ACTIVE, bumped_at__lt=threshold)
        .update(
            status=AdStatus.ARCHIVED, status_changed_at=timezone.now(), updated_at=timezone.now()
        )
    )


def archive_all_for_seller(seller) -> int:
    return Ad.objects.filter(
        seller=seller, status__in=(AdStatus.ACTIVE, AdStatus.PENDING, AdStatus.REJECTED)
    ).update(status=AdStatus.ARCHIVED, status_changed_at=timezone.now())


TRANSITIONS = {
    "withdraw": (withdraw, "Объявление снято с публикации"),
    "sold": (mark_sold, "Отлично! Объявление отмечено проданным"),
    "restore": (restore, "Объявление снова опубликовано"),
    "delete": (delete, "Объявление удалено"),
}


VIEW_TTL = 60 * 60 * 24


def register_view(request, ad: Ad) -> bool:
    if request.user.is_authenticated and request.user.pk == ad.seller_id:
        return False
    if request.user.is_authenticated:
        viewer = f"u{request.user.pk}"
    else:
        if not request.session.session_key:
            request.session.save()
        viewer = f"s{request.session.session_key}"
    key = f"ads:view:{ad.pk}:{viewer}:{timezone.localdate():%Y%m%d}"
    if not cache.add(key, 1, VIEW_TTL):
        return False
    Ad.objects.filter(pk=ad.pk).update(views_count=F("views_count") + 1)
    ad.views_count += 1
    return True


def register_phone_reveal(ad: Ad) -> None:
    Ad.objects.filter(pk=ad.pk).update(contacts_shown_count=F("contacts_shown_count") + 1)
