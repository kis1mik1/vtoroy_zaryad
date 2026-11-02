from django.contrib import admin, messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.shortcuts import render
from django.utils.html import format_html

from apps.moderation import services as moderation
from apps.moderation.admin import ModerationActionInline, ModerationCheckInline
from apps.moderation.forms import RejectForm
from apps.moderation.permissions import REVIEW_AD

from .models import Ad, AdAttributeValue, AdPhoto, AdStatus, ConditionReport, PriceChange


class AdPhotoInline(admin.TabularInline):
    model = AdPhoto
    fields = ("preview", "position", "is_flagged")
    readonly_fields = ("preview",)
    extra = 0

    @admin.display(description="фото")
    def preview(self, obj):
        return format_html('<img src="{}" width="120" alt="">', obj.thumb.url) if obj.thumb else "—"


class AdAttributeValueInline(admin.TabularInline):
    model = AdAttributeValue
    fields = ("attribute", "option", "value_number", "value_bool")
    raw_id_fields = ("option",)
    extra = 0


class ConditionReportInline(admin.StackedInline):
    model = ConditionReport
    can_delete = False


class PriceChangeInline(admin.TabularInline):
    model = PriceChange
    fields = ("created_at", "old_price", "new_price")
    readonly_fields = fields
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Ad)
class AdAdmin(admin.ModelAdmin):
    list_display = ("title", "price", "status", "category", "city", "seller", "created_at")
    list_filter = ("status", "condition", "category__parent", "city", "is_deleted")
    list_select_related = ("category", "city", "seller")
    search_fields = ("title", "description", "seller__email")
    raw_id_fields = ("seller", "device_model")
    readonly_fields = (
        "created_at",
        "updated_at",
        "published_at",
        "status_changed_at",
        "review_queued_at",
        "views_count",
        "contacts_shown_count",
        "favorites_count",
    )
    date_hierarchy = "created_at"
    inlines = [
        AdPhotoInline,
        ConditionReportInline,
        AdAttributeValueInline,
        PriceChangeInline,
        ModerationCheckInline,
        ModerationActionInline,
    ]
    actions = ["approve_ads", "reject_ads"]

    def has_review_permission(self, request):
        return request.user.has_perm(REVIEW_AD)

    @admin.action(description="Одобрить и опубликовать", permissions=["review"])
    def approve_ads(self, request, queryset):
        approved = 0
        for ad in queryset.filter(status=AdStatus.PENDING):
            moderation.approve(ad, request.user)
            approved += 1
        skipped = queryset.count() - approved
        self.message_user(request, f"Опубликовано: {approved}", messages.SUCCESS)
        if skipped:
            self.message_user(request, f"Пропущено (не на проверке): {skipped}", messages.WARNING)

    @admin.action(description="Отклонить с указанием причины", permissions=["review"])
    def reject_ads(self, request, queryset):
        queryset = queryset.filter(status__in=(AdStatus.PENDING, AdStatus.ACTIVE))
        form = RejectForm(request.POST if "apply" in request.POST else None)
        if form.is_bound and form.is_valid():
            reason, comment = form.cleaned_data["reason"], form.cleaned_data["comment"]
            for ad in queryset:
                moderation.reject(ad, request.user, reason, comment)
            self.message_user(request, f"Отклонено: {queryset.count()}", messages.SUCCESS)
            return None
        return render(
            request,
            "admin/ads/reject.html",
            {
                **self.admin_site.each_context(request),
                "title": "Отклонить объявления",
                "ads": queryset,
                "form": form,
                "action_checkbox_name": ACTION_CHECKBOX_NAME,
                "opts": self.model._meta,
            },
        )


@admin.register(AdPhoto)
class AdPhotoAdmin(admin.ModelAdmin):
    list_display = ("pk", "ad", "owner", "is_flagged", "created_at")
    list_filter = ("is_flagged",)
    raw_id_fields = ("ad", "owner")
