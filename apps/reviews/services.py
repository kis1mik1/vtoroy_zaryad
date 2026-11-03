from decimal import ROUND_HALF_UP, Decimal

from django.db import IntegrityError, transaction
from django.db.models import Avg, Count
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.chat.models import Conversation, Message, MessageKind
from apps.notifications.models import NotificationKind
from apps.notifications.services import notify

from .models import AuthorRole, Review

TWO_PLACES = Decimal("0.01")


class ReviewError(Exception):
    pass


def reviews_url(review: Review) -> str:
    return f"{reverse('reviews:list', args=[review.target_id])}#review-{review.pk}"


def _both_wrote(conversation: Conversation) -> bool:
    senders = set(
        Message.objects.filter(conversation=conversation)
        .exclude(kind=MessageKind.SYSTEM)
        .values_list("sender_id", flat=True)
        .distinct()
    )
    return {conversation.buyer_id, conversation.seller_id} <= senders


def existing_review(author, conversation: Conversation) -> Review | None:
    return Review.objects.filter(author=author, ad_id=conversation.ad_id).first()


def ensure_can_review(author, conversation: Conversation) -> None:
    if not conversation.is_participant(author):
        raise ReviewError("Оставить отзыв могут только участники переписки.")
    if existing_review(author, conversation):
        raise ReviewError("Вы уже оставили отзыв по этому объявлению.")
    if not conversation.other(author).is_active:
        raise ReviewError("Собеседник удалил аккаунт.")
    if not _both_wrote(conversation):
        raise ReviewError("Отзыв можно оставить, когда вы и собеседник обменялись сообщениями.")


def can_review(author, conversation: Conversation) -> bool:
    try:
        ensure_can_review(author, conversation)
    except ReviewError:
        return False
    return True


def recalculate_rating(user_id: int) -> None:
    User.objects.select_for_update().get(pk=user_id)
    stats = (
        Review.objects.visible()
        .filter(target_id=user_id)
        .aggregate(average=Avg("rating"), count=Count("pk"))
    )
    average = Decimal(stats["average"] or 0).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    User.objects.filter(pk=user_id).update(rating_avg=average, rating_count=stats["count"])


@transaction.atomic
def create_review(author, conversation: Conversation, *, rating: int, text: str) -> Review:
    ensure_can_review(author, conversation)
    role = AuthorRole.BUYER if author.pk == conversation.buyer_id else AuthorRole.SELLER
    try:
        with transaction.atomic():
            review = Review.objects.create(
                author=author,
                target=conversation.other(author),
                ad=conversation.ad,
                author_role=role,
                rating=rating,
                text=text.strip(),
            )
    except IntegrityError as exc:
        raise ReviewError("Вы уже оставили отзыв по этому объявлению.") from exc
    recalculate_rating(review.target_id)
    notify(
        review.target,
        NotificationKind.REVIEW,
        f"Новый отзыв: {rating} из 5",
        f"{author.first_name} оставил(а) отзыв о сделке «{conversation.ad.title}».",
        url=reviews_url(review),
    )
    return review


@transaction.atomic
def update_review(review: Review, author, *, rating: int, text: str) -> Review:
    if review.author_id != author.pk:
        raise ReviewError("Изменить можно только свой отзыв.")
    if not review.is_editable:
        raise ReviewError("Отзыв, на который уже ответили, изменить нельзя.")
    review.rating = rating
    review.text = text.strip()
    review.save(update_fields=["rating", "text", "updated_at"])
    recalculate_rating(review.target_id)
    return review


@transaction.atomic
def reply(review: Review, user, text: str) -> Review:
    if review.target_id != user.pk:
        raise ReviewError("Ответить может только тот, о ком отзыв.")
    if review.reply_text:
        raise ReviewError("Вы уже ответили на этот отзыв.")
    if review.is_hidden:
        raise ReviewError("Отзыв скрыт модератором.")
    review.reply_text = text.strip()
    review.reply_at = timezone.now()
    review.save(update_fields=["reply_text", "reply_at", "updated_at"])
    notify(
        review.author,
        NotificationKind.REVIEW,
        "Ответ на ваш отзыв",
        f"{user.first_name} ответил(а) на ваш отзыв.",
        url=reviews_url(review),
    )
    return review


@transaction.atomic
def report(review: Review, user, reason: str) -> Review:
    if review.target_id != user.pk:
        raise ReviewError("Пожаловаться на отзыв может только тот, о ком он.")
    if not review.can_be_reported:
        raise ReviewError("Модератор уже проверил этот отзыв.")
    review.reported_at = timezone.now()
    review.report_reason = reason.strip()
    review.save(update_fields=["reported_at", "report_reason", "updated_at"])
    return review


def _moderated(review: Review, moderator) -> list[str]:
    review.moderated_by = moderator
    review.moderated_at = timezone.now()
    review.reported_at = None
    return ["moderated_by", "moderated_at", "reported_at", "updated_at"]


@transaction.atomic
def hide(review: Review, moderator, reason: str) -> Review:
    if review.is_hidden:
        raise ReviewError("Отзыв уже скрыт.")
    review.is_hidden = True
    review.hidden_reason = reason.strip()
    review.save(update_fields=["is_hidden", "hidden_reason", *_moderated(review, moderator)])
    recalculate_rating(review.target_id)
    notify(
        review.author,
        NotificationKind.REVIEW,
        "Отзыв скрыт модератором",
        f"Причина: {review.hidden_reason}",
        url=reverse("core:rules"),
    )
    return review


@transaction.atomic
def restore(review: Review, moderator) -> Review:
    if not review.is_hidden:
        raise ReviewError("Отзыв не скрыт.")
    review.is_hidden = False
    review.hidden_reason = ""
    review.save(update_fields=["is_hidden", "hidden_reason", *_moderated(review, moderator)])
    recalculate_rating(review.target_id)
    return review


@transaction.atomic
def keep(review: Review, moderator) -> Review:
    if review.reported_at is None:
        raise ReviewError("На отзыв никто не жаловался.")
    review.save(update_fields=_moderated(review, moderator))
    return review
