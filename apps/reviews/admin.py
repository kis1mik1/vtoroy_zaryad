from django.contrib import admin

from .models import Review


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ("pk", "created_at", "author", "target", "rating", "is_hidden", "reported_at")
    list_filter = ("rating", "is_hidden", "author_role")
    list_select_related = ("author", "target")
    search_fields = ("text", "author__email", "target__email")
    raw_id_fields = ("author", "target", "ad", "moderated_by")
    readonly_fields = ("created_at", "updated_at", "reply_at", "reported_at", "moderated_at")
