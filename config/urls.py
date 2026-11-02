from django.conf import settings
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path
from django.views.generic import RedirectView

from apps.ads.sitemaps import AdSitemap, CategorySitemap
from apps.core.sitemaps import StaticViewSitemap

admin.site.site_header = "Второй заряд — управление"
admin.site.site_title = "Второй заряд"
admin.site.index_title = "Разделы"

sitemaps = {"static": StaticViewSitemap, "categories": CategorySitemap, "ads": AdSitemap}

urlpatterns = [
    path(settings.ADMIN_URL, admin.site.urls),
    path(
        "sitemap.xml",
        sitemap,
        {"sitemaps": sitemaps},
        name="django.contrib.sitemaps.views.sitemap",
    ),
    path("favicon.ico", RedirectView.as_view(url=f"{settings.STATIC_URL}img/favicon.ico")),
    path("account/", include("apps.accounts.urls")),
    path("notifications/", include("apps.notifications.urls")),
    path("", include("apps.ads.urls")),
    path("", include("apps.core.urls")),
]

handler400 = "apps.core.views.bad_request"
handler403 = "apps.core.views.permission_denied"
handler404 = "apps.core.views.page_not_found"
handler500 = "apps.core.views.server_error"

if settings.DEBUG:
    from django.conf.urls.static import static

    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    if "debug_toolbar" in settings.INSTALLED_APPS:
        urlpatterns.append(path("__debug__/", include("debug_toolbar.urls")))
