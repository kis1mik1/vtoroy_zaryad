from django.urls import path

from . import views

app_name = "reviews"

urlpatterns = [
    path("reviews/new/<int:conversation_pk>/", views.create, name="create"),
    path("reviews/<int:pk>/edit/", views.edit, name="edit"),
    path("reviews/<int:pk>/reply/", views.reply, name="reply"),
    path("reviews/<int:pk>/report/", views.report, name="report"),
    path("u/<int:user_pk>/reviews/", views.review_list, name="list"),
    path("moderation/reviews/", views.moderation_list, name="moderation"),
    path("moderation/reviews/<int:pk>/<slug:action>/", views.moderate, name="moderate"),
]
