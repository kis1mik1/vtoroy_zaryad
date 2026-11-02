from django import forms
from django.conf import settings
from django.contrib.auth.forms import (
    AuthenticationForm,
    BaseUserCreationForm,
    PasswordResetForm,
)
from django.urls import reverse
from django.utils.safestring import mark_safe

from apps.core.email import send_templated_email
from apps.core.forms import CaptchaMixin, CityChoiceField
from apps.core.images import open_image
from apps.core.ratelimit import FailureCounter, client_ip

from .models import ContactMode, User
from .phone import normalize_phone

LOGIN_FAILURES = FailureCounter("login-failures", ttl=60 * 60)
CAPTCHA_AFTER_FAILURES = 3


def _normalize(email: str) -> str:
    return User.objects.normalize_email(email)


class RegistrationForm(CaptchaMixin, BaseUserCreationForm):
    city = CityChoiceField()
    agree = forms.BooleanField(
        label="Согласен с правилами",
        error_messages={"required": "Без согласия с правилами регистрация невозможна."},
    )

    class Meta:
        model = User
        fields = ("first_name", "email", "city")
        labels = {"first_name": "Имя", "email": "Электронная почта"}
        help_texts = {"first_name": "Так вас увидят покупатели и продавцы."}
        widgets = {
            "first_name": forms.TextInput(attrs={"autocomplete": "given-name"}),
            "email": forms.EmailInput(attrs={"autocomplete": "email"}),
        }

    def __init__(self, *args, ip="", **kwargs):
        self.ip = ip
        super().__init__(*args, **kwargs)
        self.fields["password1"].label = "Пароль"
        self.fields[
            "password1"
        ].help_text = "Не короче 8 символов. Не только из цифр и не похож на имя или почту."
        self.fields["password2"].label = "Пароль ещё раз"
        self.fields["password2"].help_text = ""
        self.fields["agree"].label = mark_safe(
            f'Принимаю <a href="{reverse("core:terms")}" target="_blank">пользовательское '
            f'соглашение</a> и <a href="{reverse("core:rules")}" target="_blank">правила '
            "размещения</a>"
        )

    def clean_email(self):
        email = _normalize(self.cleaned_data["email"])
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError(
                "Пользователь с такой почтой уже зарегистрирован. Войдите или восстановите пароль."
            )
        return email

    def clean(self):
        cleaned = super().clean()
        self.validate_captcha(self.ip)
        return cleaned


class LoginForm(CaptchaMixin, AuthenticationForm):
    username = forms.EmailField(
        label="Электронная почта",
        widget=forms.EmailInput(attrs={"autofocus": True, "autocomplete": "email"}),
    )
    remember = forms.BooleanField(label="Запомнить меня", required=False, initial=True)

    error_messages = {
        "invalid_login": "Неверная почта или пароль.",
        "inactive": "Этот аккаунт удалён.",
    }

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        self.ip = client_ip(request) if request else ""
        self.captcha_required = self.is_bound and self._failures() >= CAPTCHA_AFTER_FAILURES

    def _ident(self) -> str:
        return f"{_normalize(self.data.get('username', ''))}|{self.ip}"

    def _failures(self) -> int:
        return LOGIN_FAILURES.count(self._ident())

    def clean(self):
        if self.captcha_required:
            self.validate_captcha(self.ip)
        try:
            cleaned = super().clean()
        except forms.ValidationError:
            failures = LOGIN_FAILURES.add(self._ident())
            self.captcha_required = failures >= CAPTCHA_AFTER_FAILURES
            raise
        LOGIN_FAILURES.clear(self._ident())
        return cleaned


class ResetPasswordForm(PasswordResetForm):
    email = forms.EmailField(
        label="Электронная почта",
        widget=forms.EmailInput(attrs={"autocomplete": "email", "autofocus": True}),
    )

    def send_mail(self, subject_template_name, email_template_name, context, *args, **kwargs):
        user = context["user"]
        path = reverse(
            "accounts:password_reset_confirm",
            kwargs={"uidb64": context["uid"], "token": context["token"]},
        )
        send_templated_email(
            user.email, "password_reset", {"user": user, "url": f"{settings.SITE_URL}{path}"}
        )


class ProfileForm(forms.ModelForm):
    city = CityChoiceField()
    phone = forms.CharField(
        label="Телефон",
        required=False,
        max_length=30,
        help_text="Покупатели увидят номер, только если выбран способ связи «Звонки и сообщения».",
        widget=forms.TextInput(
            attrs={"type": "tel", "autocomplete": "tel", "placeholder": "+7 900 000-00-00"}
        ),
    )
    avatar_file = forms.FileField(
        label="Фото",
        required=False,
        help_text="JPEG, PNG, WebP или HEIC до 15 МБ. Фото обрежем до квадрата.",
        widget=forms.ClearableFileInput(attrs={"accept": "image/*"}),
    )
    remove_avatar = forms.BooleanField(label="Удалить фото", required=False)

    class Meta:
        model = User
        fields = ("first_name", "city", "phone", "contact_mode", "about")
        labels = {"first_name": "Имя", "about": "О себе"}
        help_texts = {
            "about": "Например, чем занимаетесь или когда удобно встретиться. До 1000 символов.",
        }
        widgets = {
            "contact_mode": forms.RadioSelect,
            "about": forms.Textarea(attrs={"rows": 4, "maxlength": 1000}),
        }

    def clean_phone(self):
        return normalize_phone(self.cleaned_data.get("phone", ""))

    def clean_avatar_file(self):
        uploaded = self.cleaned_data.get("avatar_file")
        if uploaded:
            open_image(uploaded)
        return uploaded

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("contact_mode") == ContactMode.PHONE_AND_MESSAGES and not cleaned.get(
            "phone"
        ):
            self.add_error("phone", "Укажите телефон или выберите связь только через сообщения.")
        return cleaned


class NotificationSettingsForm(forms.ModelForm):
    class Meta:
        model = User
        fields = (
            "email_on_messages",
            "email_on_moderation",
            "email_on_price_drop",
            "email_on_saved_search",
        )
        labels = {
            "email_on_messages": "Новые сообщения, если не прочитали их за 10 минут",
            "email_on_moderation": "Решения по моим объявлениям",
            "email_on_price_drop": "Снижение цены на объявления в избранном",
            "email_on_saved_search": "Новые объявления по сохранённым поискам",
        }


class CurrentPasswordMixin:
    def clean_password(self):
        password = self.cleaned_data["password"]
        if not self.user.check_password(password):
            raise forms.ValidationError("Неверный пароль.")
        return password


class EmailChangeForm(CurrentPasswordMixin, forms.Form):
    new_email = forms.EmailField(
        label="Новый адрес", widget=forms.EmailInput(attrs={"autocomplete": "email"})
    )
    password = forms.CharField(
        label="Текущий пароль",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_new_email(self):
        email = _normalize(self.cleaned_data["new_email"])
        if email == self.user.email:
            raise forms.ValidationError("Это ваш текущий адрес.")
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("Этот адрес уже занят другим пользователем.")
        return email


class DeleteAccountForm(CurrentPasswordMixin, forms.Form):
    password = forms.CharField(
        label="Пароль",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )
    confirm = forms.BooleanField(
        label="Понимаю, что объявления будут сняты, а аккаунт нельзя будет восстановить",
        error_messages={"required": "Подтвердите удаление."},
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
