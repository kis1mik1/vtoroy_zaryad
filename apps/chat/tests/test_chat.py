import subprocess
from datetime import timedelta

import pytest
from asgiref.sync import async_to_sync
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.factories import UserFactory
from apps.ads.tests.factories import image_upload
from apps.ads.tests.helpers import publish
from apps.chat import services
from apps.chat.models import Conversation, Message, MessageKind
from apps.chat.routing import websocket_urlpatterns
from apps.chat.selectors import unread_count

pytestmark = pytest.mark.django_db
AJAX = {"X-Requested-With": "fetch"}


@pytest.fixture
def conversation(phones):
    ad = publish(phones)
    return services.start_conversation(ad, UserFactory(first_name="Олег"))


def voice_file(seconds=2, fmt="ogg", content_type="audio/ogg"):
    command = [
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
        "-c:a", "libopus", "-f", fmt, "-",
    ]  # fmt: skip
    data = subprocess.run(command, capture_output=True, check=True).stdout
    return SimpleUploadedFile("voice", data, content_type=content_type)


def test_write_button_opens_single_conversation(client, phones):
    ad = publish(phones)
    buyer = UserFactory()
    client.force_login(buyer)
    url = reverse("chat:start", args=[ad.pk])

    first, second = client.post(url), client.post(url)

    conversation = Conversation.objects.get()
    assert first.url == second.url == reverse("chat:conversation", args=[conversation.pk])
    assert (conversation.buyer, conversation.seller) == (buyer, ad.seller)


def test_seller_cannot_write_to_himself(client, phones):
    ad = publish(phones)
    client.force_login(ad.seller)

    client.post(reverse("chat:start", args=[ad.pk]))

    assert not Conversation.objects.exists()


def test_outsider_sees_nothing(client, conversation):
    message = services.send_photo(conversation, conversation.buyer, image_upload())
    client.force_login(UserFactory())

    assert client.get(reverse("chat:conversation", args=[conversation.pk])).status_code == 404
    assert client.get(reverse("chat:file", args=[message.pk])).status_code == 404


def test_participants_get_protected_photo(client, conversation):
    message = services.send_photo(conversation, conversation.buyer, image_upload())

    for user in (conversation.buyer, conversation.seller):
        client.force_login(user)
        response = client.get(reverse("chat:file", args=[message.pk]))
        assert response.status_code == 200
        assert response["Cache-Control"] == "private, max-age=86400"
    assert message.file.name.endswith(".webp")


def test_accel_redirect_in_production(client, conversation, settings):
    settings.PROTECTED_MEDIA_ACCEL_PREFIX = "/protected-internal/"
    message = services.send_photo(conversation, conversation.buyer, image_upload())
    client.force_login(conversation.seller)

    response = client.get(reverse("chat:file", args=[message.pk]))

    assert response["X-Accel-Redirect"] == f"/protected-internal/{message.file.name}"


def test_send_text_and_read(client, conversation):
    client.force_login(conversation.buyer)

    response = client.post(
        reverse("chat:send", args=[conversation.pk]), {"text": "Ещё продаёте?"}, headers=AJAX
    )

    assert "Ещё продаёте?" in response.content.decode()
    assert unread_count(conversation.seller) == 1
    client.force_login(conversation.seller)
    page = client.get(reverse("chat:conversation", args=[conversation.pk])).content.decode()
    assert "Ещё продаёте?" in page
    assert unread_count(conversation.seller) == 0
    assert Message.objects.get().read_at is not None


def test_conversation_list_shows_unread(client, conversation):
    services.send_text(conversation, conversation.buyer, "Добрый день")
    client.force_login(conversation.seller)

    page = client.get(reverse("chat:list")).content.decode()

    assert "Олег" in page
    assert "Добрый день" in page
    assert 'class="counter">1<' in page


@pytest.mark.parametrize(
    "text",
    [
        "Оформите доставку по ссылке, я пришлю",
        "Переведите на карту 2202 2061 2345 6789",
        "Вот ссылка на оплату: pay-delivery.ru/order",
        "Пришлите код из смс",
    ],
)
def test_fraud_warning_for_recipient_only(client, conversation, text):
    services.send_text(conversation, conversation.seller, text)

    client.force_login(conversation.buyer)
    assert (
        "Осторожно"
        in client.get(reverse("chat:conversation", args=[conversation.pk])).content.decode()
    )
    client.force_login(conversation.seller)
    assert (
        "Осторожно"
        not in client.get(reverse("chat:conversation", args=[conversation.pk])).content.decode()
    )


def test_ordinary_message_is_not_suspicious(conversation):
    message = services.send_text(
        conversation, conversation.buyer, "Можно посмотреть завтра в 18:00?"
    )

    assert not message.is_suspicious


def test_block_stops_both_sides(client, conversation):
    client.force_login(conversation.seller)
    client.post(reverse("chat:block", args=[conversation.pk]))

    for user in (conversation.buyer, conversation.seller):
        with pytest.raises(services.ChatError):
            services.send_text(conversation, user, "Привет")

    page = client.get(reverse("chat:conversation", args=[conversation.pk])).content.decode()
    assert "Вы заблокировали собеседника" in page
    client.post(reverse("chat:block", args=[conversation.pk]), {"action": "unblock"})
    assert services.send_text(conversation, conversation.buyer, "Привет")


def test_hidden_conversation_returns_with_new_message(client, conversation):
    services.send_text(conversation, conversation.buyer, "Здравствуйте")
    client.force_login(conversation.seller)
    client.post(reverse("chat:hide", args=[conversation.pk]))
    assert "Олег" not in client.get(reverse("chat:list")).content.decode()

    services.send_text(conversation, conversation.buyer, "Вы тут?")

    assert "Олег" in client.get(reverse("chat:list")).content.decode()


def test_voice_is_transcoded_to_m4a(conversation, run_on_commit):
    with run_on_commit():
        message = services.send_voice(conversation, conversation.buyer, voice_file(seconds=2))

    message.refresh_from_db()
    assert message.is_ready
    assert message.kind == MessageKind.VOICE
    assert message.duration == 2
    assert message.file.name.endswith(".m4a")
    assert message.file.read(12)[4:8] == b"ftyp"


def test_broken_voice_is_dropped(conversation, run_on_commit):
    broken = SimpleUploadedFile("voice", b"not an audio file", content_type="audio/webm")

    with run_on_commit():
        services.send_voice(conversation, conversation.buyer, broken)

    assert not Message.objects.exists()


def test_voice_rejects_other_files(conversation):
    with pytest.raises(services.ChatError):
        services.send_voice(conversation, conversation.buyer, image_upload())


def test_unread_email_after_ten_minutes(conversation, run_on_commit):
    message = services.send_text(conversation, conversation.buyer, "Когда можно забрать?")
    Message.objects.filter(pk=message.pk).update(created_at=timezone.now() - timedelta(minutes=11))

    with run_on_commit():
        assert services.email_unread_messages() == 1
        assert services.email_unread_messages() == 0
    assert conversation.seller.email in mail.outbox[0].to
    assert "Когда можно забрать" not in mail.outbox[0].body
    assert reverse("chat:conversation", args=[conversation.pk]) in mail.outbox[0].body


def test_unread_email_respects_settings(conversation):
    conversation.seller.email_on_messages = False
    conversation.seller.save()
    message = services.send_text(conversation, conversation.buyer, "Привет")
    Message.objects.filter(pk=message.pk).update(created_at=timezone.now() - timedelta(minutes=11))

    assert services.email_unread_messages() == 0
    assert not mail.outbox


def _socket(user, conversation_id):
    communicator = WebsocketCommunicator(
        URLRouter(websocket_urlpatterns), f"/ws/chat/{conversation_id}/"
    )
    communicator.scope["user"] = user
    return communicator


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_websocket_delivers_messages_to_both(conversation):
    buyer, seller = conversation.buyer, conversation.seller

    async def scenario():
        mine, other = _socket(buyer, conversation.pk), _socket(seller, conversation.pk)
        assert (await mine.connect())[0]
        assert (await other.connect())[0]
        await mine.send_json_to({"type": "send", "text": "Торг возможен?"})
        sent, received = await mine.receive_json_from(), await other.receive_json_from()
        await other.send_json_to({"type": "read"})
        read = await mine.receive_json_from()
        await mine.send_json_to({"type": "send", "text": "   "})
        error = await mine.receive_json_from()
        await mine.disconnect()
        await other.disconnect()
        return sent, received, read, error

    sent, received, read, error = async_to_sync(scenario)()

    assert "msg--mine" in sent["html"]
    assert "Торг возможен?" in received["html"]
    assert "msg--mine" not in received["html"]
    assert read == {"type": "read"}
    assert error["type"] == "error"
    assert Message.objects.get().read_at is not None


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_websocket_closed_for_outsiders(conversation):
    outsider = UserFactory()

    async def scenario():
        communicator = _socket(outsider, conversation.pk)
        result = await communicator.connect()
        await communicator.disconnect()
        return result

    assert async_to_sync(scenario)() == (False, 4403)
