from django.contrib import admin, messages

from . import services
from .gateway import GatewayError
from .models import Payment, PromotionTariff


@admin.register(PromotionTariff)
class PromotionTariffAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "price",
        "bump",
        "highlight_days",
        "pin_days",
        "is_active",
        "sort_order",
    )
    list_editable = ("price", "is_active", "sort_order")
    prepopulated_fields = {"code": ("title",)}


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("pk", "created_at", "user", "tariff", "amount", "status", "is_test", "paid_at")
    list_filter = ("status", "is_test", "tariff")
    list_select_related = ("user", "tariff")
    search_fields = ("pk", "provider_payment_id", "user__email", "description")
    date_hierarchy = "created_at"
    readonly_fields = [field.name for field in Payment._meta.fields]
    actions = ["sync_with_provider"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Сверить статус с ЮKassa")
    def sync_with_provider(self, request, queryset):
        synced = failed = 0
        for payment in queryset.filter(provider_payment_id__isnull=False):
            try:
                services.sync_payment(payment)
            except GatewayError:
                failed += 1
            else:
                synced += 1
        self.message_user(request, f"Сверено платежей: {synced}")
        if failed:
            self.message_user(request, f"Не удалось сверить: {failed}", messages.WARNING)
