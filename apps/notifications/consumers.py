from channels.generic.websocket import AsyncJsonWebsocketConsumer

from .services import user_group


class UserEventsConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        if user is None or not user.is_authenticated:
            await self.close(code=4401)
            return
        self.group = user_group(user.pk)
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        if hasattr(self, "group"):
            await self.channel_layer.group_discard(self.group, self.channel_name)

    async def receive_json(self, content, **kwargs):
        return

    async def notification_created(self, event):
        await self.send_json(
            {
                "type": "notification",
                "unread": event["unread"],
                "title": event["title"],
                "url": event["url"],
                "html": event["html"],
            }
        )

    async def notification_read(self, event):
        await self.send_json({"type": "notification_read", "unread": event["unread"]})
