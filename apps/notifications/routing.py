from django.urls import path

from .consumers import UserEventsConsumer

websocket_urlpatterns = [path("ws/notifications/", UserEventsConsumer.as_asgi())]
