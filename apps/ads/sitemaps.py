from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from apps.catalog.models import Category

from .models import Ad


class AdSitemap(Sitemap):
    changefreq = "daily"
    priority = 0.7
    limit = 5000

    def items(self):
        return Ad.objects.visible().only("pk", "slug", "updated_at").order_by("-bumped_at")

    def location(self, ad):
        return reverse("ads:detail", args=[ad.pk, ad.slug])

    def lastmod(self, ad):
        return ad.updated_at


class CategorySitemap(Sitemap):
    changefreq = "daily"
    priority = 0.8

    def items(self):
        return Category.objects.filter(is_active=True).order_by("sort_order")

    def location(self, category):
        return reverse("ads:category", args=[category.slug])
