from django.urls import path

from . import views

app_name = "ads"

urlpatterns = [
    path("ad/new/", views.ad_create, name="create"),
    path("ad/<int:pk>/edit/", views.ad_edit, name="edit"),
    path("ad/<int:pk>/status/<slug:action>/", views.ad_status, name="status"),
    path("ad/form/section/", views.ad_form_section, name="form_section"),
    path("ad/photos/", views.photo_upload, name="photo_upload"),
    path("my/ads/", views.my_ads, name="my_ads"),
]
