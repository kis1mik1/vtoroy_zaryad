from django.contrib import admin

from . import services
from .models import FAQItem, FAQSection, SupportTicket, TicketReply


class FAQItemInline(admin.StackedInline):
    model = FAQItem
    extra = 0
    fields = ("question", "answer", "sort_order", "is_published")


@admin.register(FAQSection)
class FAQSectionAdmin(admin.ModelAdmin):
    list_display = ("title", "sort_order", "is_published")
    list_editable = ("sort_order", "is_published")
    prepopulated_fields = {"slug": ("title",)}
    inlines = [FAQItemInline]


@admin.register(FAQItem)
class FAQItemAdmin(admin.ModelAdmin):
    list_display = ("question", "section", "sort_order", "is_published")
    list_filter = ("section", "is_published")
    list_editable = ("sort_order", "is_published")
    search_fields = ("question", "answer")


class ReplyHistoryInline(admin.TabularInline):
    model = TicketReply
    verbose_name_plural = "ответы"
    fields = ("created_at", "author", "message")
    readonly_fields = fields
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


class NewReplyInline(admin.StackedInline):
    model = TicketReply
    verbose_name = "новый ответ"
    verbose_name_plural = "новый ответ (уйдёт пользователю письмом)"
    fields = ("message",)
    extra = 1
    max_num = 1
    can_delete = False

    def get_queryset(self, request):
        return super().get_queryset(request).none()


@admin.register(SupportTicket)
class SupportTicketAdmin(admin.ModelAdmin):
    list_display = ("pk", "created_at", "subject", "topic", "email", "status")
    list_filter = ("status", "topic")
    list_select_related = ("user",)
    search_fields = ("pk", "subject", "message", "email")
    date_hierarchy = "created_at"
    fields = ("status", "topic", "name", "email", "user", "subject", "message", "created_at")
    readonly_fields = ("topic", "name", "email", "user", "subject", "message", "created_at")
    inlines = [ReplyHistoryInline, NewReplyInline]

    def has_add_permission(self, request):
        return False

    def save_formset(self, request, form, formset, change):
        if formset.model is not TicketReply:
            return super().save_formset(request, form, formset, change)
        for reply in formset.save(commit=False):
            if reply.pk is None and reply.message.strip():
                services.reply(form.instance, request.user, reply.message)
        return None
