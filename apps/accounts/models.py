from django.contrib.auth.models import AbstractUser
from django.db import models

from .managers import UserManager


class User(AbstractUser):
    username = None
    email = models.EmailField(
        "электронная почта",
        unique=True,
        error_messages={"unique": "Пользователь с такой почтой уже зарегистрирован."},
    )
    first_name = models.CharField("имя", max_length=60)

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["first_name"]

    objects = UserManager()

    class Meta:
        verbose_name = "пользователь"
        verbose_name_plural = "пользователи"
        ordering = ("-date_joined",)

    def __str__(self):
        return self.email

    def clean(self):
        super().clean()
        self.email = type(self).objects.normalize_email(self.email)

    def get_full_name(self):
        return self.first_name

    def get_short_name(self):
        return self.first_name
