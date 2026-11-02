from django.contrib import admin

from .models import City


@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    list_display = ("name", "region", "slug", "sort_order", "is_default")
    list_editable = ("sort_order",)
    list_filter = ("region",)
    search_fields = ("name", "region")
    prepopulated_fields = {"slug": ("name",)}
