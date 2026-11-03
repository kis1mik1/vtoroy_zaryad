import re
import secrets
import subprocess
import tempfile
from collections import defaultdict
from datetime import timedelta
from functools import partial
from pathlib import Path

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.core.files import File
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from apps.core.email import send_templated_email
from apps.core.images import fit_within, open_image, to_webp
from apps.core.ratelimit import Rate, hit
from apps.moderation.rules import TEXT_RULES
from apps.moderation.text import normalize
from apps.notifications.models import NotificationKind
from apps.notifications.services import push_to_user, wants_email

from .models import Conversation, Message, MessageKind, UserBlock
from .selectors import unread_count

MESSAGE_RATE = Rate(limit=30, period=60)
MAX_TEXT = 2000
PHOTO_SIZE = 1600
VOICE_MAX_BYTES = 5 * 1024 * 1024
VOICE_MAX_SECONDS = 120
VOICE_TYPES = ("audio/", "video/webm", "application/octet-stream")
UNREAD_EMAIL_AFTER = timedelta(minutes=10)
FRAUD_RULES = {"link", "handle", "prepayment", "card"}
FRAUD_PHRASES = re.compile(
    r"\b(?:оформ\w+|оплат\w+|получ\w+) (?:\w+ ){0,3}(?:доставк\w*|заказ\w*) (?:по|через) ссылк\w*"
    r"|\bссылк\w* (?:на|для) (?:оплат\w*|доставк\w*|получени\w*)"
    r"|\bкод из (?:смс|sms)|\bданные карты|\bcvv|\bсрок действия карты"
)


class ChatError(Exception):
    pass


def conversation_group(conversation_id: int) -> str:
    return f"chat_{conversation_id}"


def broadcast(conversation_id: int, event: dict) -> None:
    layer = get_channel_layer()
    if layer is not None:
        async_to_sync(layer.group_send)(conversation_group(conversation_id), event)


def push_unread(user_id: int) -> None:
    push_to_user(user_id, {"type": "messages.unread", "unread": unread_count(user_id)})


def looks_suspicious(text: str) -> bool:
    normalized = normalize(text)
    if FRAUD_PHRASES.search(normalized):
        return True
    return any(rule.code in FRAUD_RULES and rule.pattern.search(normalized) for rule in TEXT_RULES)


def is_blocked(first_id: int, second_id: int) -> bool:
    return UserBlock.objects.filter(
        Q(user_id=first_id, blocked_user_id=second_id)
        | Q(user_id=second_id, blocked_user_id=first_id)
    ).exists()


@transaction.atomic
def start_conversation(ad, buyer) -> Conversation:
    if ad.seller_id == buyer.pk:
        raise ChatError("Это ваше объявление.")
    conversation, _ = Conversation.objects.get_or_create(
        ad=ad, buyer=buyer, defaults={"seller_id": ad.seller_id}
    )
    if conversation.buyer_hidden:
        conversation.buyer_hidden = False
        conversation.save(update_fields=["buyer_hidden", "updated_at"])
    return conversation


def ensure_can_send(conversation: Conversation, sender) -> None:
    if not conversation.is_participant(sender):
        raise ChatError("Вы не участвуете в этом диалоге.")
    if is_blocked(conversation.buyer_id, conversation.seller_id):
        raise ChatError("Переписка недоступна: собеседник заблокирован.")
    if not conversation.other(sender).is_active:
        raise ChatError("Собеседник удалил аккаунт.")
    hit("chat-send", f"user:{sender.pk}", MESSAGE_RATE)


def _recipient_id(message: Message) -> int:
    conversation = message.conversation
    return (
        conversation.buyer_id
        if message.sender_id == conversation.seller_id
        else conversation.seller_id
    )


def _announce(message: Message) -> None:
    broadcast(message.conversation_id, {"type": "chat.message", "id": message.pk})
    push_unread(_recipient_id(message))


def _deliver(message: Message) -> None:
    Conversation.objects.filter(pk=message.conversation_id).update(
        last_message_at=message.created_at, buyer_hidden=False, seller_hidden=False
    )
    if message.is_ready:
        transaction.on_commit(partial(_announce, message))


@transaction.atomic
def send_text(conversation: Conversation, sender, text: str) -> Message:
    text = text.strip()
    if not text:
        raise ChatError("Напишите что-нибудь.")
    if len(text) > MAX_TEXT:
        raise ChatError(f"Сообщение длиннее {MAX_TEXT} символов.")
    ensure_can_send(conversation, sender)
    message = Message.objects.create(
        conversation=conversation,
        sender=sender,
        kind=MessageKind.TEXT,
        text=text,
        is_suspicious=looks_suspicious(text),
    )
    _deliver(message)
    return message


@transaction.atomic
def send_photo(conversation: Conversation, sender, uploaded) -> Message:
    ensure_can_send(conversation, sender)
    image = fit_within(open_image(uploaded), PHOTO_SIZE)
    message = Message(
        conversation=conversation,
        sender=sender,
        kind=MessageKind.PHOTO,
        width=image.width,
        height=image.height,
    )
    message.file.save(f"{secrets.token_hex(10)}.webp", to_webp(image), save=False)
    message.save()
    _deliver(message)
    return message


@transaction.atomic
def send_voice(conversation: Conversation, sender, uploaded) -> Message:
    ensure_can_send(conversation, sender)
    if uploaded.size > VOICE_MAX_BYTES:
        raise ChatError("Голосовое слишком большое.")
    if not (uploaded.content_type or "").startswith(VOICE_TYPES):
        raise ChatError("Это не похоже на запись голоса.")
    message = Message(
        conversation=conversation, sender=sender, kind=MessageKind.VOICE, is_ready=False
    )
    message.file.save(f"{secrets.token_hex(10)}.upload", uploaded, save=False)
    message.save()
    _deliver(message)
    from .tasks import transcode_voice

    transaction.on_commit(partial(transcode_voice.delay, message.pk))
    return message


def _ffmpeg(source: Path, target: Path) -> bool:
    command = [
        "ffmpeg", "-y", "-v", "error", "-i", str(source), "-t", str(VOICE_MAX_SECONDS),
        "-vn", "-ac", "1", "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", str(target),
    ]  # fmt: skip
    result = subprocess.run(command, capture_output=True, timeout=120, check=False)
    return result.returncode == 0 and target.exists() and target.stat().st_size > 0


def _duration(path: Path) -> float | None:
    command = [
        "ffprobe", "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    ]  # fmt: skip
    result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    try:
        return float(result.stdout.strip().splitlines()[0])
    except (ValueError, IndexError):
        return None


def transcode(message_id: int) -> bool:
    message = (
        Message.objects.select_related("conversation")
        .filter(pk=message_id, kind=MessageKind.VOICE, is_ready=False)
        .first()
    )
    if message is None:
        return False
    storage, original = message.file.storage, message.file.name
    with tempfile.TemporaryDirectory() as folder:
        source, target = Path(folder) / "source", Path(folder) / "voice.m4a"
        with storage.open(original, "rb") as uploaded:
            source.write_bytes(uploaded.read())
        duration = _duration(target) if _ffmpeg(source, target) else None
        if not duration:
            storage.delete(original)
            conversation_id, sender_id = message.conversation_id, message.sender_id
            message.delete()
            broadcast(conversation_id, {"type": "chat.failed", "sender": sender_id})
            return False
        with target.open("rb") as converted:
            message.file.save(f"{secrets.token_hex(10)}.m4a", File(converted), save=False)
    message.duration = max(1, round(duration))
    message.is_ready = True
    message.save(update_fields=["file", "duration", "is_ready"])
    storage.delete(original)
    _announce(message)
    return True


@transaction.atomic
def mark_read(conversation: Conversation, reader) -> int:
    updated = (
        conversation.messages.filter(read_at__isnull=True, is_ready=True)
        .exclude(sender=reader)
        .update(read_at=timezone.now())
    )
    if updated:
        conversation_id, reader_id = conversation.pk, reader.pk
        transaction.on_commit(
            lambda: (
                broadcast(conversation_id, {"type": "chat.read", "reader": reader_id}),
                push_unread(reader_id),
            )
        )
    return updated


def hide(conversation: Conversation, user) -> None:
    field = conversation.hidden_field(user)
    setattr(conversation, field, True)
    conversation.save(update_fields=[field, "updated_at"])
    mark_read(conversation, user)


def block(user, other) -> None:
    if user.pk == other.pk:
        raise ChatError("Себя заблокировать нельзя.")
    UserBlock.objects.get_or_create(user=user, blocked_user=other)


def unblock(user, other) -> None:
    UserBlock.objects.filter(user=user, blocked_user=other).delete()


def email_unread_messages() -> int:
    pending = list(
        Message.objects.filter(
            read_at__isnull=True,
            emailed=False,
            is_ready=True,
            sender__isnull=False,
            created_at__lte=timezone.now() - UNREAD_EMAIL_AFTER,
        ).select_related(
            "conversation__ad", "conversation__buyer", "conversation__seller", "sender"
        )
    )
    by_recipient: dict = defaultdict(list)
    for message in pending:
        recipient = message.conversation.other(message.sender)
        by_recipient[recipient].append(message)
    sent = 0
    for recipient, messages in by_recipient.items():
        if not wants_email(recipient, NotificationKind.MESSAGE):
            continue
        conversations = {message.conversation for message in messages}
        send_templated_email(
            recipient.email,
            "unread_messages",
            {
                "user": recipient,
                "count": len(messages),
                "conversations": [
                    (
                        c.ad.title,
                        c.other(recipient).first_name,
                        f"{settings.SITE_URL}{reverse('chat:conversation', args=[c.pk])}",
                    )
                    for c in conversations
                ],
                "settings_url": f"{settings.SITE_URL}{reverse('accounts:settings_notifications')}",
            },
        )
        sent += 1
    Message.objects.filter(pk__in=[message.pk for message in pending]).update(emailed=True)
    return sent
