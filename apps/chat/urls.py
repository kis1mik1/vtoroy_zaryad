from django.urls import path

from . import views

app_name = "chat"

urlpatterns = [
    path("messages/", views.conversation_list, name="list"),
    path("messages/<int:pk>/", views.conversation, name="conversation"),
    path("messages/<int:pk>/send/", views.send, name="send"),
    path("messages/<int:pk>/photo/", views.send_photo, name="photo"),
    path("messages/<int:pk>/voice/", views.send_voice, name="voice"),
    path("messages/<int:pk>/hide/", views.hide, name="hide"),
    path("messages/<int:pk>/block/", views.block, name="block"),
    path("messages/file/<int:pk>/", views.message_file, name="file"),
    path("ad/<int:pk>/write/", views.start, name="start"),
]
