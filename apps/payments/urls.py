from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("ad/<int:pk>/promote/", views.promote, name="promote"),
    path("payments/<int:pk>/return/", views.payment_return, name="return"),
    path("payments/<int:pk>/status/", views.payment_status, name="status"),
    path("payments/webhook/", views.webhook, name="webhook"),
    path("my/payments/", views.history, name="history"),
]
