from django.urls import path

from . import views

app_name = "moderation"

urlpatterns = [
    path("moderation/", views.queue, name="queue"),
    path("moderation/rejected/", views.rejected, name="rejected"),
    path("moderation/history/", views.history, name="history"),
    path("moderation/ads/<int:pk>/", views.ad_review, name="ad"),
    path("moderation/ads/<int:pk>/decide/", views.ad_decide, name="ad_decide"),
    path("moderation/complaints/", views.complaints, name="complaints"),
    path(
        "moderation/complaints/<slug:kind>/<int:pk>/dismiss/",
        views.complaints_dismiss,
        name="complaints_dismiss",
    ),
    path("moderation/users/<int:pk>/", views.user_card, name="user"),
    path("moderation/users/<int:pk>/ban/", views.user_ban, name="user_ban"),
    path("moderation/users/<int:pk>/unban/", views.user_unban, name="user_unban"),
    path("ad/<int:pk>/complain/", views.complain_ad, name="complain_ad"),
    path("u/<int:pk>/complain/", views.complain_user, name="complain_user"),
]
