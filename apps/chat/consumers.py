from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.template.loader import render_to_string

from apps.core.ratelimit import RateLimited

from . import selectors, services
from .models import Message

MAX_INCOMING = 4000


class ChatConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.user = self.scope.get("user")
        if self.user is None or not self.user.is_authenticated or self.user.is_banned:
            await self.close(code=4401)
            return
        pk = self.scope["url_route"]["kwargs"]["pk"]
        self.conversation = await database_sync_to_async(selectors.conversation_for)(self.user, pk)
        if self.conversation is None:
            await self.close(code=4403)
            return
        self.group = services.conversation_group(self.conversation.pk)
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        if hasattr(self, "group"):
            await self.channel_layer.group_discard(self.group, self.channel_name)

    async def receive_json(self, content, **kwargs):
        action = content.get("type")
        if action == "send":
            text = str(content.get("text", ""))[:MAX_INCOMING]
            try:
                await database_sync_to_async(services.send_text)(self.conversation, self.user, text)
            except services.ChatError as exc:
                await self.send_json({"type": "error", "text": str(exc)})
            except RateLimited as exc:
                await self.send_json({"type": "error", "text": exc.message})
        elif action == "read":
            await database_sync_to_async(services.mark_read)(self.conversation, self.user)

    def render(self, message_id: int) -> str:
        message = (
            Message.objects.select_related("sender")
            .filter(pk=message_id, conversation_id=self.conversation.pk, is_ready=True)
            .first()
        )
        if message is None:
            return ""
        return render_to_string(
            "chat/partials/message.html", {"message": message, "viewer": self.user}
        )

    async def chat_message(self, event):
        html = await database_sync_to_async(self.render)(event["id"])
        if html:
            await self.send_json({"type": "message", "id": event["id"], "html": html})

    async def chat_read(self, event):
        if event["reader"] != self.user.pk:
            await self.send_json({"type": "read"})

    async def chat_failed(self, event):
        if event["sender"] == self.user.pk:
            await self.send_json(
                {"type": "error", "text": "Не удалось обработать голосовое, запишите его ещё раз."}
            )
