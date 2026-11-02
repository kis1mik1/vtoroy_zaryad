from django.db import models
from django.db.models import Q


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField("создано", auto_now_add=True)
    updated_at = models.DateTimeField("изменено", auto_now=True)

    class Meta:
        abstract = True


class City(models.Model):
    name = models.CharField("название", max_length=100)
    slug = models.SlugField("адрес в ссылке", max_length=100, unique=True)
    region = models.CharField("регион", max_length=100)
    sort_order = models.PositiveSmallIntegerField("порядок", default=0)
    is_default = models.BooleanField("город по умолчанию", default=False)

    class Meta:
        verbose_name = "город"
        verbose_name_plural = "города"
        ordering = ("sort_order", "name")
        constraints = [
            models.UniqueConstraint(
                fields=("is_default",),
                condition=Q(is_default=True),
                name="city_single_default",
            ),
        ]

    def __str__(self):
        return self.name
