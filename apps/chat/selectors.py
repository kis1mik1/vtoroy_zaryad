from django.db.models import Count, OuterRef, Prefetch, Q, Subquery

from apps.ads.models import AdPhoto

from .models import Conversation, Message

HISTORY_SIZE = 200


def _user_id(user) -> int:
    return getattr(user, "pk", user)


def unread_messages(user):
    user_id = _user_id(user)
    return (
        Message.objects.filter(
            Q(conversation__buyer_id=user_id) | Q(conversation__seller_id=user_id),
            read_at__isnull=True,
            is_ready=True,
        )
        .exclude(sender_id=user_id)
        .exclude(sender__isnull=True)
    )


def unread_count(user) -> int:
    return unread_messages(user).count()


def conversations_for(user):
    last = Message.objects.filter(conversation=OuterRef("pk"), is_ready=True).order_by(
        "-created_at", "-pk"
    )
    unread = Q(messages__read_at__isnull=True, messages__is_ready=True) & ~Q(messages__sender=user)
    return (
        Conversation.objects.filter(
            Q(buyer=user, buyer_hidden=False) | Q(seller=user, seller_hidden=False),
            last_message_at__isnull=False,
        )
        .select_related("ad", "buyer", "seller")
        .prefetch_related(
            Prefetch(
                "ad__photos",
                queryset=AdPhoto.objects.order_by("position", "pk"),
                to_attr="ordered_photos",
            )
        )
        .annotate(
            unread=Count("messages", filter=unread),
            last_text=Subquery(last.values("text")[:1]),
            last_kind=Subquery(last.values("kind")[:1]),
            last_sender=Subquery(last.values("sender_id")[:1]),
        )
        .order_by("-last_message_at")
    )


def conversation_for(user, pk: int) -> Conversation | None:
    return (
        Conversation.objects.filter(Q(buyer=user) | Q(seller=user), pk=pk)
        .select_related("ad__city", "buyer", "seller")
        .prefetch_related(
            Prefetch(
                "ad__photos",
                queryset=AdPhoto.objects.order_by("position", "pk"),
                to_attr="ordered_photos",
            )
        )
        .first()
    )


def history(conversation) -> list[Message]:
    recent = conversation.messages.filter(is_ready=True).order_by("-created_at", "-pk")
    return list(recent[:HISTORY_SIZE])[::-1]
