from django.contrib.sitemaps import Sitemap
from django.urls import reverse


class StaticViewSitemap(Sitemap):
    changefreq = "monthly"

    def items(self):
        return [
            "core:home",
            "core:rules",
            "core:safety",
            "core:terms",
            "core:privacy",
            "core:about",
        ]

    def location(self, item):
        return reverse(item)

    def priority(self, item):
        return 1.0 if item == "core:home" else 0.4
