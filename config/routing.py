from apps.chat.routing import websocket_urlpatterns as chat_patterns
from apps.notifications.routing import websocket_urlpatterns as notification_patterns

websocket_urlpatterns = [*notification_patterns, *chat_patterns]
