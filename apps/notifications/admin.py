from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "kind", "is_read", "created_at")
    list_filter = ("kind", "is_read")
    list_select_related = ("user",)
    search_fields = ("title", "user__email")
    raw_id_fields = ("user",)
    date_hierarchy = "created_at"
