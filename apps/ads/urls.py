from django.urls import path

from .views import browse, lists, seller

app_name = "ads"

urlpatterns = [
    path("", browse.home, name="home"),
    path("search/", browse.search, name="search"),
    path("c/<slug:category_slug>/", browse.search, name="category"),
    path("ad/new/", seller.ad_create, name="create"),
    path("ad/<int:pk>-<slug:slug>/", browse.ad_detail, name="detail"),
    path("ad/<int:pk>/edit/", seller.ad_edit, name="edit"),
    path("ad/<int:pk>/status/<slug:action>/", seller.ad_status, name="status"),
    path("ad/<int:pk>/phone/", browse.ad_phone, name="phone"),
    path("ad/<int:pk>/favorite/", lists.favorite_toggle, name="favorite"),
    path("ad/form/section/", seller.ad_form_section, name="form_section"),
    path("ad/photos/", seller.photo_upload, name="photo_upload"),
    path("compare/", lists.compare, name="compare"),
    path("compare/clear/", lists.compare_clear, name="compare_clear"),
    path("compare/<int:pk>/", lists.compare_toggle, name="compare_toggle"),
    path("u/<int:pk>/", browse.user_profile, name="profile"),
    path("my/ads/", seller.my_ads, name="my_ads"),
    path("my/ads/<int:pk>/row/", seller.my_ad_row, name="my_ad_row"),
    path("my/favorites/", lists.my_favorites, name="favorites"),
    path("my/searches/", lists.my_searches, name="saved_searches"),
    path("my/searches/save/", lists.saved_search_create, name="saved_search_create"),
    path(
        "my/searches/<int:pk>/<slug:action>/", lists.saved_search_update, name="saved_search_update"
    ),
]
