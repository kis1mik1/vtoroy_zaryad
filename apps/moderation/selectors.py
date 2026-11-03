from dataclasses import dataclass, field
from datetime import timedelta

from django.db.models import Count, Exists, OuterRef, Prefetch, Q
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.ads.models import CHECK_TIMEOUT, Ad, AdPhoto, AdStatus
from apps.ads.selectors import with_market
from apps.reviews.models import Review

from .ml import images
from .ml.text import load_text_classifier
from .models import (
    ActionKind,
    Complaint,
    ComplaintStatus,
    ModerationAction,
    ModerationCheck,
    Verdict,
)

AUTO_REJECTED_WINDOW = timedelta(days=7)


def _with_review_data(queryset):
    return (
        queryset.select_related(
            "seller", "category__parent", "city", "device_model__brand", "brand"
        )
        .prefetch_related(
            Prefetch(
                "photos",
                queryset=AdPhoto.objects.order_by("position", "pk"),
                to_attr="ordered_photos",
            ),
            Prefetch(
                "checks",
                queryset=ModerationCheck.objects.order_by("-created_at", "-pk"),
                to_attr="check_list",
            ),
        )
        .annotate(
            open_complaints=Count("complaints", filter=Q(complaints__status=ComplaintStatus.NEW))
        )
    )


def review_queue():
    stuck_before = timezone.now() - CHECK_TIMEOUT
    return (
        _with_review_data(Ad.objects.alive())
        .filter(status=AdStatus.PENDING)
        .filter(Q(review_queued_at__isnull=False) | Q(status_changed_at__lt=stuck_before))
        .order_by(Coalesce("review_queued_at", "status_changed_at"), "pk")
    )


def auto_rejected():
    manual = ModerationAction.objects.filter(
        ad=OuterRef("pk"), created_at__gte=OuterRef("status_changed_at")
    )
    return (
        _with_review_data(Ad.objects.alive())
        .filter(
            status=AdStatus.REJECTED,
            status_changed_at__gte=timezone.now() - AUTO_REJECTED_WINDOW,
            checks__verdict=Verdict.REJECTED,
        )
        .exclude(Exists(manual))
        .distinct()
        .order_by("-status_changed_at")
    )


def ad_for_review(pk: int) -> Ad:
    return (
        _with_review_data(with_market(Ad.objects.alive()))
        .prefetch_related("attribute_values__attribute", "attribute_values__option")
        .get(pk=pk)
    )


def ad_history(ad: Ad) -> list:
    actions = list(ad.moderation_actions.select_related("moderator"))
    events = [("check", check.created_at, check) for check in ad.check_list]
    events += [("action", action.created_at, action) for action in actions]
    return sorted(events, key=lambda event: event[1], reverse=True)


@dataclass
class ComplaintGroup:
    kind: str
    target: object
    complaints: list = field(default_factory=list)

    @property
    def first_at(self):
        return min(complaint.created_at for complaint in self.complaints)

    @property
    def reasons(self) -> list[str]:
        return sorted({complaint.get_reason_display() for complaint in self.complaints})


def complaint_groups(status: str = ComplaintStatus.NEW, limit: int = 100) -> list[ComplaintGroup]:
    complaints = (
        Complaint.objects.filter(status=status)
        .select_related("author", "ad__seller", "ad__city", "target_user", "handled_by")
        .prefetch_related(
            Prefetch(
                "ad__photos",
                queryset=AdPhoto.objects.order_by("position", "pk"),
                to_attr="ordered_photos",
            )
        )
        .order_by("created_at" if status == ComplaintStatus.NEW else "-handled_at")[: limit * 5]
    )
    groups: dict[tuple[str, int], ComplaintGroup] = {}
    for complaint in complaints:
        if complaint.ad_id:
            key = ("ad", complaint.ad_id)
            group = groups.setdefault(key, ComplaintGroup("ad", complaint.ad))
        else:
            key = ("user", complaint.target_user_id)
            group = groups.setdefault(key, ComplaintGroup("user", complaint.target_user))
        group.complaints.append(complaint)
    return list(groups.values())[:limit]


def user_complaints(user):
    return (
        Complaint.objects.filter(Q(target_user=user) | Q(ad__seller=user))
        .select_related("author", "ad", "handled_by")
        .order_by("-created_at")
    )


def user_ads(user):
    return Ad.objects.alive().filter(seller=user).select_related("category").order_by("-created_at")


def user_summary(user) -> dict:
    ads = Ad.objects.alive().filter(seller=user)
    counts = ads.aggregate(
        total=Count("pk"),
        active=Count("pk", filter=Q(status=AdStatus.ACTIVE)),
        pending=Count("pk", filter=Q(status=AdStatus.PENDING)),
        rejected=Count("pk", filter=Q(status=AdStatus.REJECTED)),
    )
    counts["taken_down"] = ModerationAction.objects.filter(
        ad__seller=user, action__in=(ActionKind.REJECT, ActionKind.TAKE_DOWN)
    ).count()
    counts["complaints"] = user_complaints(user).count()
    return counts


def counters() -> dict:
    open_complaints = Complaint.objects.filter(status=ComplaintStatus.NEW)
    return {
        "queue": review_queue().count(),
        "complaints": open_complaints.values("ad_id", "target_user_id").distinct().count(),
        "reviews": Review.objects.reported().count(),
    }


def today_stats() -> dict:
    since = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    checks = ModerationCheck.objects.filter(created_at__gte=since)
    return checks.aggregate(
        checked=Count("pk"),
        approved=Count("pk", filter=Q(verdict=Verdict.APPROVED)),
        manual=Count("pk", filter=Q(verdict=Verdict.MANUAL)),
        rejected=Count("pk", filter=Q(verdict=Verdict.REJECTED)),
    )


def recent_actions():
    return ModerationAction.objects.select_related("ad", "moderator").order_by("-created_at", "-pk")


@dataclass(frozen=True)
class ModelsStatus:
    text_ready: bool
    text_note: str
    images_ready: bool
    images_note: str


def models_status() -> ModelsStatus:
    classifier = load_text_classifier()
    if classifier is None:
        text_ready, text_note = False, "Не обучен: python manage.py train_text_classifier"
    else:
        hard = classifier.meta.get("hard") or {}
        holdout = classifier.meta.get("holdout") or {}
        text_note = f"Отложенная выборка {round(holdout.get('accuracy', 0) * 100)}%"
        if hard:
            text_note += f", трудный набор {round(hard.get('accuracy', 0) * 100)}%"
        text_ready = True
    images_ready, images_note = images.availability()
    return ModelsStatus(text_ready, text_note, images_ready, images_note)
