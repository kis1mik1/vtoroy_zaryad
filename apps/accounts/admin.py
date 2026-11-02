from django import forms
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import AdminUserCreationForm, UserChangeForm
from django.utils import timezone

from . import services
from .models import BanRecord, User


class UserCreationForm(AdminUserCreationForm):
    class Meta:
        model = User
        fields = ("email", "first_name", "city")


class UserEditForm(UserChangeForm):
    class Meta:
        model = User
        fields = "__all__"


class BanRecordInline(admin.TabularInline):
    model = BanRecord
    fk_name = "user"
    extra = 0
    can_delete = False
    fields = ("created_at", "reason", "until", "moderator", "lifted_at", "lifted_by")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


class VerifiedFilter(admin.SimpleListFilter):
    title = "почта"
    parameter_name = "verified"

    def lookups(self, request, model_admin):
        return [("yes", "подтверждена"), ("no", "не подтверждена")]

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(email_verified_at__isnull=False)
        if self.value() == "no":
            return queryset.filter(email_verified_at__isnull=True)
        return queryset


class BannedFilter(admin.SimpleListFilter):
    title = "блокировка"
    parameter_name = "banned"

    def lookups(self, request, model_admin):
        return [("yes", "заблокированы"), ("no", "без блокировки")]

    def queryset(self, request, queryset):
        now = timezone.now()
        if self.value() == "yes":
            return queryset.filter(banned_until__gt=now)
        if self.value() == "no":
            return queryset.exclude(banned_until__gt=now)
        return queryset


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    form = UserEditForm
    add_form = UserCreationForm
    inlines = [BanRecordInline]
    ordering = ("-date_joined",)
    list_display = (
        "email",
        "first_name",
        "city",
        "is_verified",
        "is_banned_now",
        "is_staff",
        "date_joined",
        "last_seen_at",
    )
    list_filter = (VerifiedFilter, BannedFilter, "is_staff", "is_active", "groups", "city")
    list_select_related = ("city",)
    search_fields = ("email", "first_name", "phone")
    readonly_fields = (
        "date_joined",
        "last_login",
        "last_seen_at",
        "deleted_at",
        "rating_avg",
        "rating_count",
        "banned_until",
        "ban_reason",
    )
    actions = ["mark_email_verified", "lift_bans"]
    fieldsets = (
        (None, {"fields": ("email", "password", "email_verified_at")}),
        ("Профиль", {"fields": ("first_name", "city", "phone", "contact_mode", "avatar", "about")}),
        (
            "Письма",
            {
                "fields": (
                    "email_on_messages",
                    "email_on_price_drop",
                    "email_on_saved_search",
                    "email_on_moderation",
                )
            },
        ),
        ("Рейтинг", {"fields": ("rating_avg", "rating_count")}),
        ("Блокировка", {"fields": ("banned_until", "ban_reason")}),
        (
            "Права",
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        ("Даты", {"fields": ("date_joined", "last_login", "last_seen_at", "deleted_at")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "first_name", "city", "password1", "password2"),
            },
        ),
    )

    @admin.display(description="почта", boolean=True, ordering="email_verified_at")
    def is_verified(self, obj):
        return obj.is_email_verified

    @admin.display(description="заблокирован", boolean=True, ordering="banned_until")
    def is_banned_now(self, obj):
        return obj.is_banned

    @admin.action(description="Отметить почту подтверждённой")
    def mark_email_verified(self, request, queryset):
        count = queryset.filter(email_verified_at__isnull=True).update(
            email_verified_at=timezone.now()
        )
        self.message_user(request, f"Подтверждено адресов: {count}", messages.SUCCESS)

    @admin.action(description="Снять блокировку")
    def lift_bans(self, request, queryset):
        users = [user for user in queryset if user.banned_until]
        for user in users:
            services.lift_ban(user, moderator=request.user)
        self.message_user(request, f"Разблокировано: {len(users)}", messages.SUCCESS)


class BanForm(forms.ModelForm):
    class Meta:
        model = BanRecord
        fields = ("user", "reason", "until")

    def clean_until(self):
        until = self.cleaned_data["until"]
        if until and until <= timezone.now():
            raise forms.ValidationError("Дата окончания должна быть в будущем.")
        return until


@admin.register(BanRecord)
class BanRecordAdmin(admin.ModelAdmin):
    form = BanForm
    list_display = ("user", "reason", "until", "moderator", "created_at", "lifted_at")
    list_select_related = ("user", "moderator")
    search_fields = ("user__email", "reason")
    autocomplete_fields = ("user",)
    list_filter = ("lifted_at",)

    def has_change_permission(self, request, obj=None):
        return obj is None and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        record = services.ban_user(
            obj.user,
            reason=obj.reason,
            until=obj.until,
            moderator=request.user,
        )
        obj.pk = record.pk
