from datetime import datetime

from django.conf import settings
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from apps.accounts import services as accounts_services
from apps.accounts.models import User
from apps.ads import services as ads_services
from apps.ads.models import Ad, AdPhoto, AdStatus
from apps.catalog.models import Category
from apps.core.text import format_day
from apps.notifications.models import NotificationKind
from apps.notifications.services import notify

from . import pipeline
from .ml.text import OTHER
from .models import (
    ActionKind,
    Complaint,
    ComplaintStatus,
    ModerationAction,
    ModerationCheck,
    RejectionReason,
    Verdict,
)

COMPLAINTS_TO_REVIEW = 3


class ModerationError(Exception):
    pass


def _root_categories() -> dict[str, Category]:
    return {category.slug: category for category in Category.objects.filter(parent__isnull=True)}


def run_auto_check(ad_id: int) -> ModerationCheck | None:
    ad = (
        Ad.objects.alive()
        .select_related("category__parent", "seller")
        .filter(pk=ad_id, status=AdStatus.PENDING, review_queued_at__isnull=True)
        .first()
    )
    if ad is None:
        return None
    submitted_at = ad.status_changed_at
    roots = _root_categories()
    inspection = pipeline.inspect(ad)
    decision = pipeline.decide(
        ad, inspection, {slug: category.name for slug, category in roots.items()}
    )

    with transaction.atomic():
        locked = Ad.objects.select_for_update().get(pk=ad.pk)
        if (
            locked.status != AdStatus.PENDING
            or locked.review_queued_at is not None
            or locked.status_changed_at != submitted_at
        ):
            return None
        text = inspection.text
        check = ModerationCheck.objects.create(
            ad=locked,
            verdict=decision.verdict,
            rule_flags=[flag.as_dict() for flag in inspection.flags],
            text_label=text.label if text else "",
            text_confidence=text.confidence if text else None,
            electronics_score=text.electronics if text else None,
            predicted_category=roots.get(text.label) if text and text.label != OTHER else None,
            image_scores=[
                {
                    "photo": photo.photo_id,
                    "score": round(photo.electronics, 4),
                    "label": photo.label,
                    "flagged": photo.photo_id in decision.flagged_photos,
                }
                for photo in inspection.photos or []
            ],
            reasons=decision.reasons,
            rejection_reason=decision.message,
            duration_ms=inspection.duration_ms,
        )
        photos = AdPhoto.objects.filter(ad=locked)
        photos.exclude(pk__in=decision.flagged_photos).update(is_flagged=False)
        photos.filter(pk__in=decision.flagged_photos).update(is_flagged=True)

        if decision.verdict == Verdict.APPROVED:
            ads_services.approve(locked)
        elif decision.verdict == Verdict.REJECTED:
            ads_services.reject(locked, decision.message)
        else:
            ads_services.queue_for_review(locked)
    return check


def rejection_message(reason_code: str, comment: str = "") -> str:
    comment = comment.strip()
    if reason_code == RejectionReason.OTHER:
        return comment
    label = RejectionReason(reason_code).label
    return f"{label}. {comment}" if comment else label


def _log(ad, moderator, action, reason_code="", comment="") -> ModerationAction:
    return ModerationAction.objects.create(
        ad=ad, moderator=moderator, action=action, reason_code=reason_code, comment=comment
    )


def close_complaints(queryset, moderator, status: str) -> int:
    complaints = list(queryset.filter(status=ComplaintStatus.NEW).select_related("author"))
    if not complaints:
        return 0
    now = timezone.now()
    Complaint.objects.filter(pk__in=[c.pk for c in complaints]).update(
        status=status, handled_by=moderator, handled_at=now
    )
    if status == ComplaintStatus.ACCEPTED:
        for complaint in complaints:
            _thank_author(complaint)
    return len(complaints)


def _thank_author(complaint: Complaint) -> None:
    if complaint.ad_id:
        body = f"Объявление «{complaint.ad.title}» снято с публикации. Спасибо, что помогаете."
    else:
        body = "Пользователь, на которого вы пожаловались, заблокирован. Спасибо, что помогаете."
    notify(complaint.author, NotificationKind.MODERATION, "Жалоба рассмотрена", body)


@transaction.atomic
def approve(ad: Ad, moderator) -> Ad:
    action = ActionKind.RESTORE if ad.status == AdStatus.REJECTED else ActionKind.APPROVE
    try:
        ad = ads_services.approve(ad)
    except ads_services.TransitionError as exc:
        raise ModerationError(str(exc)) from exc
    _log(ad, moderator, action)
    close_complaints(Complaint.objects.filter(ad=ad), moderator, ComplaintStatus.DISMISSED)
    return ad


@transaction.atomic
def reject(ad: Ad, moderator, reason_code: str, comment: str = "") -> Ad:
    action = ActionKind.TAKE_DOWN if ad.status == AdStatus.ACTIVE else ActionKind.REJECT
    try:
        ad = ads_services.reject(ad, rejection_message(reason_code, comment))
    except ads_services.TransitionError as exc:
        raise ModerationError(str(exc)) from exc
    _log(ad, moderator, action, reason_code, comment.strip())
    close_complaints(Complaint.objects.filter(ad=ad), moderator, ComplaintStatus.ACCEPTED)
    return ad


@transaction.atomic
def send_to_review(ad: Ad, moderator, explanation: str, comment: str = "") -> Ad:
    try:
        ad = ads_services.send_to_review(ad, explanation)
    except ads_services.TransitionError as exc:
        raise ModerationError(str(exc)) from exc
    _log(ad, moderator, ActionKind.REVIEW, comment=comment)
    return ad


def _check_target(author, ad: Ad | None, user: User | None) -> None:
    if ad is not None:
        if ad.seller_id == author.pk:
            raise ModerationError("На своё объявление пожаловаться нельзя.")
        if ad.status != AdStatus.ACTIVE or ad.is_deleted:
            raise ModerationError("Объявление уже снято с публикации.")
        if Complaint.objects.filter(author=author, ad=ad).exists():
            raise ModerationError("Вы уже пожаловались на это объявление.")
    else:
        if user.pk == author.pk:
            raise ModerationError("Пожаловаться на себя нельзя.")
        if Complaint.objects.filter(
            author=author, target_user=user, status=ComplaintStatus.NEW
        ).exists():
            raise ModerationError("Ваша жалоба на этого пользователя уже на рассмотрении.")


@transaction.atomic
def file_complaint(author, *, reason: str, comment: str = "", ad=None, user=None) -> Complaint:
    if (ad is None) == (user is None):
        raise ValueError("Нужно указать либо объявление, либо пользователя.")
    _check_target(author, ad, user)
    try:
        with transaction.atomic():
            complaint = Complaint.objects.create(
                author=author, ad=ad, target_user=user, reason=reason, comment=comment.strip()
            )
    except IntegrityError as exc:
        raise ModerationError("Вы уже отправили такую жалобу.") from exc
    if ad is not None:
        _review_if_many_complaints(ad)
    return complaint


def _review_if_many_complaints(ad: Ad) -> None:
    ad = Ad.objects.select_for_update().get(pk=ad.pk)
    if ad.status != AdStatus.ACTIVE:
        return
    authors = (
        Complaint.objects.filter(ad=ad, status=ComplaintStatus.NEW)
        .values("author")
        .distinct()
        .count()
    )
    if authors >= COMPLAINTS_TO_REVIEW:
        send_to_review(
            ad,
            None,
            "На объявление пожаловались покупатели. Модератор проверит его в течение рабочего дня.",
            comment=f"Жалоб от разных покупателей: {authors}",
        )


@transaction.atomic
def dismiss_complaints(moderator, *, ad=None, user=None) -> int:
    queryset = Complaint.objects.filter(ad=ad) if ad else Complaint.objects.filter(target_user=user)
    return close_complaints(queryset, moderator, ComplaintStatus.DISMISSED)


def _ban_period(until: datetime | None) -> str:
    if until is None:
        return "навсегда"
    return f"до {format_day(timezone.localtime(until).date(), with_year=True)}"


@transaction.atomic
def ban(user: User, moderator, *, reason: str, until: datetime | None):
    if user.pk == moderator.pk:
        raise ModerationError("Себя заблокировать нельзя.")
    if user.is_staff or user.is_superuser:
        raise ModerationError("Сотрудников сайта блокирует только администратор.")
    if user.is_deleted:
        raise ModerationError("Аккаунт уже удалён.")
    record = accounts_services.ban_user(user, reason=reason, until=until, moderator=moderator)
    close_complaints(
        Complaint.objects.filter(target_user=user), moderator, ComplaintStatus.ACCEPTED
    )
    notify(
        user,
        NotificationKind.ACCOUNT,
        "Аккаунт заблокирован",
        f"Причина: {reason}\nСрок: {_ban_period(until)}.\n"
        f"Если считаете решение ошибочным, напишите на {settings.SUPPORT_EMAIL}.",
        url=reverse("core:rules"),
    )
    return record


@transaction.atomic
def lift_ban(user: User, moderator) -> None:
    if not user.banned_until:
        raise ModerationError("Пользователь не заблокирован.")
    accounts_services.lift_ban(user, moderator=moderator)
    notify(
        user,
        NotificationKind.ACCOUNT,
        "Блокировка снята",
        "Вы снова можете размещать объявления и писать продавцам.",
    )
