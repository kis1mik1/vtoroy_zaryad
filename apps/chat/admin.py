from django.contrib import admin

from .models import Conversation, Message, UserBlock


class MessageInline(admin.TabularInline):
    model = Message
    fields = ("created_at", "sender", "kind", "text", "is_suspicious", "read_at")
    readonly_fields = fields
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("ad", "buyer", "seller", "last_message_at")
    list_select_related = ("ad", "buyer", "seller")
    search_fields = ("ad__title", "buyer__email", "seller__email")
    raw_id_fields = ("ad", "buyer", "seller")
    inlines = [MessageInline]


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("__str__", "conversation", "sender", "kind", "is_suspicious", "created_at")
    list_filter = ("kind", "is_suspicious")
    list_select_related = ("conversation", "sender")
    search_fields = ("text", "sender__email")
    raw_id_fields = ("conversation", "sender")


@admin.register(UserBlock)
class UserBlockAdmin(admin.ModelAdmin):
    list_display = ("user", "blocked_user", "created_at")
    raw_id_fields = ("user", "blocked_user")
