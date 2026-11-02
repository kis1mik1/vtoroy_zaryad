from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("register/", views.RegisterView.as_view(), name="register"),
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("verify/sent/", views.verify_sent, name="verify_sent"),
    path("verify/resend/", views.verify_resend, name="verify_resend"),
    path("verify/<str:token>/", views.verify_email, name="verify_email"),
    path("password/reset/", views.PasswordResetView.as_view(), name="password_reset"),
    path(
        "password/reset/sent/",
        views.PasswordResetDoneView.as_view(),
        name="password_reset_done",
    ),
    path(
        "password/reset/<uidb64>/<token>/",
        views.PasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        "password/reset/complete/",
        views.PasswordResetCompleteView.as_view(),
        name="password_reset_complete",
    ),
    path("settings/", views.profile_settings, name="settings"),
    path("settings/notifications/", views.notification_settings, name="settings_notifications"),
    path("security/", views.security, name="security"),
    path("password/change/", views.password_change, name="password_change"),
    path("email/change/", views.email_change, name="email_change"),
    path("email/confirm/<str:token>/", views.email_change_confirm, name="confirm_email_change"),
    path("delete/", views.delete_account, name="delete"),
]
