from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from django.views.generic import FormView

from apps.core.decorators import ratelimit
from apps.core.ratelimit import Rate, RateLimited, client_ip, hit
from apps.notifications.models import NotificationKind
from apps.notifications.services import notify

from . import services
from .forms import (
    DeleteAccountForm,
    EmailChangeForm,
    LoginForm,
    NotificationSettingsForm,
    ProfileForm,
    RegistrationForm,
    ResetPasswordForm,
)
from .tokens import InvalidToken

REGISTER_RATE = Rate(limit=5, period=60 * 60)
LOGIN_IP_RATE = Rate(limit=30, period=15 * 60)
RESET_IP_RATE = Rate(limit=5, period=60 * 60)
RESEND_SHORT_RATE = Rate(limit=1, period=60)
RESEND_LONG_RATE = Rate(limit=5, period=60 * 60)
EMAIL_CHANGE_RATE = Rate(limit=5, period=60 * 60)

SETTINGS_SECTIONS = (
    ("accounts:settings", "Профиль", "user"),
    ("accounts:settings_notifications", "Письма", "mail"),
    ("accounts:security", "Почта и пароль", "lock"),
    ("accounts:delete", "Удаление аккаунта", "trash-2"),
)


def settings_context(request, title, **extra):
    return {
        "title": title,
        "sections": [(reverse(name), label, icon) for name, label, icon in SETTINGS_SECTIONS],
        "breadcrumbs": [("Настройки", reverse("accounts:settings")), (title, None)],
        **extra,
    }


@method_decorator(ratelimit("register", REGISTER_RATE), name="post")
class RegisterView(FormView):
    template_name = "accounts/register.html"
    form_class = RegistrationForm

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("accounts:settings")
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        return {"city": self.request.city}

    def form_valid(self, form):
        user = services.register_user(
            email=form.cleaned_data["email"],
            password=form.cleaned_data["password1"],
            first_name=form.cleaned_data["first_name"],
            city=form.cleaned_data["city"],
        )
        login(self.request, user, backend="django.contrib.auth.backends.ModelBackend")
        return redirect("accounts:verify_sent")


class LoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    form_class = LoginForm
    redirect_authenticated_user = True

    def get_initial(self):
        return {"username": self.request.GET.get("email", "")}

    def post(self, request, *args, **kwargs):
        try:
            hit("login-ip", f"ip:{client_ip(request)}", LOGIN_IP_RATE)
        except RateLimited as exc:
            context = self.get_context_data(form=self.get_form(), rate_limited=exc.message)
            response = self.render_to_response(context, status=429)
            response["Retry-After"] = str(exc.retry_after)
            return response
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)
        if not form.cleaned_data.get("remember"):
            self.request.session.set_expiry(0)
        return response


class LogoutView(auth_views.LogoutView):
    pass


@login_required
@require_GET
def verify_sent(request):
    if request.user.is_email_verified:
        return redirect("accounts:settings")
    return render(request, "accounts/verify_sent.html")


@login_required
@require_POST
def verify_resend(request):
    if request.user.is_email_verified:
        messages.info(request, "Почта уже подтверждена")
        return redirect("accounts:settings")
    ident = f"user:{request.user.pk}"
    hit("verify-resend-short", ident, RESEND_SHORT_RATE)
    hit("verify-resend-long", ident, RESEND_LONG_RATE)
    services.send_verification_email(request.user)
    messages.success(request, f"Письмо отправлено на {request.user.email}")
    return redirect("accounts:verify_sent")


@require_GET
def verify_email(request, token):
    try:
        user, verified_now = services.verify_email(token)
    except InvalidToken as exc:
        return render(request, "accounts/link_invalid.html", {"error": exc.message}, status=400)
    if verified_now:
        notify(
            user,
            NotificationKind.ACCOUNT,
            "Почта подтверждена",
            "Теперь можно размещать объявления и писать продавцам.",
            email=False,
        )
        messages.success(request, "Почта подтверждена. Добро пожаловать!")
    else:
        messages.info(request, "Почта уже была подтверждена")
    if request.user.is_authenticated and request.user.pk == user.pk:
        return redirect("accounts:settings")
    return redirect(f"{reverse('accounts:login')}?email={user.email}")


@method_decorator(ratelimit("password-reset", RESET_IP_RATE), name="post")
class PasswordResetView(auth_views.PasswordResetView):
    template_name = "accounts/password_reset.html"
    form_class = ResetPasswordForm
    success_url = reverse_lazy("accounts:password_reset_done")


class PasswordResetDoneView(auth_views.PasswordResetDoneView):
    template_name = "accounts/password_reset_done.html"


class PasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = "accounts/password_reset_confirm.html"
    success_url = reverse_lazy("accounts:password_reset_complete")

    def form_valid(self, form):
        response = super().form_valid(form)
        notify(form.user, NotificationKind.ACCOUNT, "Пароль восстановлен", email=False)
        return response


class PasswordResetCompleteView(auth_views.PasswordResetCompleteView):
    template_name = "accounts/password_reset_complete.html"


@login_required
@require_http_methods(["GET", "POST"])
def profile_settings(request):
    form = ProfileForm(request.POST or None, request.FILES or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        if form.cleaned_data.get("avatar_file"):
            services.set_avatar(user, form.cleaned_data["avatar_file"])
        elif form.cleaned_data.get("remove_avatar"):
            services.remove_avatar(user)
        messages.success(request, "Профиль сохранён")
        return redirect("accounts:settings")
    if request.method == "POST":
        request.user.refresh_from_db()
    return render(
        request, "accounts/settings_profile.html", settings_context(request, "Профиль", form=form)
    )


@login_required
@require_http_methods(["GET", "POST"])
def notification_settings(request):
    form = NotificationSettingsForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Настройки писем сохранены")
        return redirect("accounts:settings_notifications")
    return render(
        request,
        "accounts/settings_notifications.html",
        settings_context(request, "Письма", form=form),
    )


def _security_page(request, password_form=None, email_form=None, status=200):
    return render(
        request,
        "accounts/settings_security.html",
        settings_context(
            request,
            "Почта и пароль",
            password_form=password_form or PasswordChangeForm(request.user),
            email_form=email_form or EmailChangeForm(request.user),
        ),
        status=status,
    )


@login_required
@require_GET
def security(request):
    return _security_page(request)


@login_required
@require_POST
def password_change(request):
    form = PasswordChangeForm(request.user, request.POST)
    if not form.is_valid():
        return _security_page(request, password_form=form)
    user = form.save()
    update_session_auth_hash(request, user)
    services.notify_password_changed(user)
    notify(user, NotificationKind.ACCOUNT, "Пароль изменён", email=False)
    messages.success(request, "Пароль изменён")
    return redirect("accounts:security")


@login_required
@require_POST
@ratelimit("email-change", EMAIL_CHANGE_RATE, key="user")
def email_change(request):
    form = EmailChangeForm(request.user, request.POST)
    if not form.is_valid():
        return _security_page(request, email_form=form)
    services.request_email_change(request.user, form.cleaned_data["new_email"])
    messages.success(
        request,
        f"Письмо со ссылкой отправлено на {form.cleaned_data['new_email']}. "
        "Адрес сменится после подтверждения.",
    )
    return redirect("accounts:security")


@require_GET
def email_change_confirm(request, token):
    try:
        user = services.confirm_email_change(token)
    except InvalidToken as exc:
        return render(request, "accounts/link_invalid.html", {"error": exc.message}, status=400)
    except services.EmailTaken:
        return render(
            request,
            "accounts/link_invalid.html",
            {"error": "Этот адрес уже занят другим пользователем."},
            status=400,
        )
    notify(user, NotificationKind.ACCOUNT, f"Адрес почты изменён на {user.email}", email=False)
    messages.success(request, f"Теперь для входа используется {user.email}")
    if request.user.is_authenticated and request.user.pk == user.pk:
        return redirect("accounts:security")
    return redirect(f"{reverse('accounts:login')}?email={user.email}")


@login_required
@require_http_methods(["GET", "POST"])
def delete_account(request):
    form = DeleteAccountForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        services.delete_account(request.user)
        logout(request)
        messages.success(request, "Аккаунт удалён. Спасибо, что были с нами.")
        return redirect("core:home")
    return render(
        request,
        "accounts/settings_delete.html",
        settings_context(request, "Удаление аккаунта", form=form),
    )
