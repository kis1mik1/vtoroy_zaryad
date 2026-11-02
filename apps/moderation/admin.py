from django.contrib import admin, messages
from django.utils.html import format_html_join

from . import services
from .models import Complaint, ComplaintStatus, ModerationAction, ModerationCheck


class ReadOnlyMixin:
    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.display(description="что вызвало сомнение")
def reasons_list(obj):
    return format_html_join("", "<div>{}</div>", ((reason,) for reason in obj.reasons)) or "—"


class ModerationCheckInline(ReadOnlyMixin, admin.TabularInline):
    model = ModerationCheck
    fields = ("created_at", "verdict", "text_label", "electronics_score", reasons_list)
    readonly_fields = fields
    extra = 0


class ModerationActionInline(ReadOnlyMixin, admin.TabularInline):
    model = ModerationAction
    fields = ("created_at", "action", "reason_code", "comment", "moderator")
    readonly_fields = fields
    extra = 0


@admin.register(ModerationCheck)
class ModerationCheckAdmin(ReadOnlyMixin, admin.ModelAdmin):
    list_display = ("ad", "verdict", "text_label", "electronics_score", "duration_ms", "created_at")
    list_filter = ("verdict", "text_label")
    list_select_related = ("ad",)
    search_fields = ("ad__title",)
    date_hierarchy = "created_at"
    fields = (
        "ad",
        "verdict",
        "created_at",
        "duration_ms",
        "text_label",
        "text_confidence",
        "electronics_score",
        "predicted_category",
        reasons_list,
        "rejection_reason",
        "rule_flags",
        "image_scores",
    )
    readonly_fields = fields


@admin.register(ModerationAction)
class ModerationActionAdmin(ReadOnlyMixin, admin.ModelAdmin):
    list_display = ("ad", "action", "reason_code", "moderator", "created_at")
    list_filter = ("action", "reason_code")
    list_select_related = ("ad", "moderator")
    search_fields = ("ad__title", "moderator__email")
    date_hierarchy = "created_at"


@admin.register(Complaint)
class ComplaintAdmin(admin.ModelAdmin):
    list_display = ("__str__", "reason", "author", "status", "created_at", "handled_by")
    list_filter = ("status", "reason")
    list_select_related = ("author", "ad", "target_user", "handled_by")
    search_fields = ("comment", "author__email", "ad__title", "target_user__email")
    raw_id_fields = ("author", "ad", "target_user")
    readonly_fields = ("handled_by", "handled_at", "created_at")
    actions = ["dismiss"]

    def has_add_permission(self, request):
        return False

    @admin.action(description="Отклонить жалобы", permissions=["change"])
    def dismiss(self, request, queryset):
        count = services.close_complaints(queryset, request.user, ComplaintStatus.DISMISSED)
        self.message_user(request, f"Отклонено жалоб: {count}", messages.SUCCESS)
