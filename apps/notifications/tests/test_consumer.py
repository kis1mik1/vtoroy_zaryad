import pytest
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from django.contrib.auth.models import AnonymousUser

from apps.accounts.models import User
from apps.notifications.consumers import UserEventsConsumer
from apps.notifications.services import user_group


async def _connect(user):
    communicator = WebsocketCommunicator(UserEventsConsumer.as_asgi(), "/ws/notifications/")
    communicator.scope["user"] = user
    connected, code = await communicator.connect()
    return communicator, connected, code


@pytest.mark.django_db
def test_anonymous_connection_rejected():
    async def scenario():
        communicator, connected, code = await _connect(AnonymousUser())
        await communicator.disconnect()
        return connected, code

    connected, code = async_to_sync(scenario)()

    assert not connected
    assert code == 4401


@pytest.mark.django_db
def test_user_receives_own_events_only():
    user = User(pk=101, email="buyer@example.com")
    stranger = User(pk=102, email="seller@example.com")

    async def scenario():
        mine, connected, _ = await _connect(user)
        other, _, _ = await _connect(stranger)
        layer = get_channel_layer()
        await layer.group_send(
            user_group(user.pk),
            {
                "type": "notification.created",
                "unread": 3,
                "title": "Новое сообщение",
                "url": "/notifications/1/open/",
                "html": "<a>Новое сообщение</a>",
            },
        )
        received = await mine.receive_json_from(timeout=1)
        nothing = await other.receive_nothing(timeout=0.2)
        await layer.group_send(user_group(user.pk), {"type": "notification.read", "unread": 0})
        read = await mine.receive_json_from(timeout=1)
        await mine.disconnect()
        await other.disconnect()
        return connected, received, nothing, read

    connected, received, nothing, read = async_to_sync(scenario)()

    assert connected
    assert received["type"] == "notification"
    assert received["unread"] == 3
    assert received["title"] == "Новое сообщение"
    assert nothing
    assert read == {"type": "notification_read", "unread": 0}


def test_websocket_route_registered():
    from config.routing import websocket_urlpatterns

    assert any(str(p.pattern) == "ws/notifications/" for p in websocket_urlpatterns)
