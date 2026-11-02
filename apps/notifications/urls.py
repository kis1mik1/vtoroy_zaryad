from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [
    path("", views.notification_list, name="list"),
    path("dropdown/", views.notification_dropdown, name="dropdown"),
    path("read-all/", views.notification_read_all, name="read_all"),
    path("<int:pk>/open/", views.notification_open, name="open"),
]
