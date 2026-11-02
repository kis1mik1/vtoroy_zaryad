from datetime import timedelta

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.catalog.models import AttributeValueMixin
from apps.core.models import TimeStampedModel

MAX_PRICE = 10_000_000
MAX_PHOTOS = 10
CHECK_TIMEOUT = timedelta(minutes=10)


class AdStatus(models.TextChoices):
    PENDING = "pending", "На проверке"
    ACTIVE = "active", "Активно"
    REJECTED = "rejected", "Отклонено"
    SOLD = "sold", "Продано"
    ARCHIVED = "archived", "В архиве"


class Condition(models.TextChoices):
    NEW = "new", "Новое"
    USED = "used", "Б/у"


class AdQuerySet(models.QuerySet):
    def alive(self):
        return self.filter(is_deleted=False)

    def visible(self):
        now = timezone.now()
        return self.alive().filter(
            Q(seller__banned_until__isnull=True) | Q(seller__banned_until__lte=now),
            status=AdStatus.ACTIVE,
            seller__is_active=True,
        )


class Ad(TimeStampedModel):
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="продавец",
        on_delete=models.CASCADE,
        related_name="ads",
    )
    category = models.ForeignKey(
        "catalog.Category", verbose_name="категория", on_delete=models.PROTECT, related_name="ads"
    )
    device_model = models.ForeignKey(
        "catalog.DeviceModel",
        verbose_name="модель",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ads",
    )
    brand = models.ForeignKey(
        "catalog.Brand",
        verbose_name="бренд",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ads",
    )
    custom_model_name = models.CharField("модель (свободно)", max_length=120, blank=True)
    title = models.CharField("название", max_length=120)
    slug = models.SlugField("адрес в ссылке", max_length=120)
    description = models.TextField("описание", max_length=5000)
    price = models.PositiveIntegerField("цена, ₽")
    is_negotiable = models.BooleanField("торг уместен", default=False)
    condition = models.CharField("состояние", max_length=10, choices=Condition)
    city = models.ForeignKey(
        "core.City", verbose_name="город", on_delete=models.PROTECT, related_name="ads"
    )

    status = models.CharField(
        "статус", max_length=10, choices=AdStatus, default=AdStatus.PENDING, db_index=True
    )
    rejection_reason = models.TextField("причина отклонения", blank=True)
    published_at = models.DateTimeField("опубликовано", null=True, blank=True)
    bumped_at = models.DateTimeField("поднято", null=True, blank=True)
    status_changed_at = models.DateTimeField("статус изменён", default=timezone.now)
    review_queued_at = models.DateTimeField("ждёт модератора с", null=True, blank=True)
    highlighted_until = models.DateTimeField("выделено до", null=True, blank=True)
    pinned_until = models.DateTimeField("закреплено до", null=True, blank=True)

    views_count = models.PositiveIntegerField("просмотры", default=0)
    contacts_shown_count = models.PositiveIntegerField("показы телефона", default=0)
    favorites_count = models.PositiveIntegerField("в избранном", default=0)
    is_deleted = models.BooleanField("удалено", default=False)
    price_key = models.PositiveIntegerField("ключ рыночной цены", default=0)
    search_text = models.TextField("текст для поиска", blank=True)
    search_vector = SearchVectorField(null=True, editable=False)

    objects = AdQuerySet.as_manager()

    class Meta:
        verbose_name = "объявление"
        verbose_name_plural = "объявления"
        ordering = ("-created_at",)
        indexes = [
            models.Index(
                fields=["status", "category", "-bumped_at"], name="ad_status_category_idx"
            ),
            models.Index(fields=["status", "city", "-bumped_at"], name="ad_status_city_idx"),
            models.Index(fields=["seller", "status"], name="ad_seller_status_idx"),
            models.Index(fields=["status", "-pinned_until", "-bumped_at"], name="ad_feed_idx"),
            models.Index(fields=["device_model", "condition", "price_key"], name="ad_market_idx"),
            models.Index(
                fields=["review_queued_at"],
                condition=Q(status="pending"),
                name="ad_review_queue_idx",
            ),
            GinIndex(fields=["search_vector"], name="ad_search_vector_idx"),
            GinIndex(fields=["search_text"], opclasses=["gin_trgm_ops"], name="ad_search_trgm_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(price__gt=0) & Q(price__lte=MAX_PRICE), name="ad_price_range"
            ),
        ]

    def __str__(self):
        return self.title

    @property
    def model_name(self) -> str:
        if self.device_model_id:
            return self.device_model.full_name
        return " ".join(
            filter(None, [self.brand.name if self.brand_id else "", self.custom_model_name])
        )

    @property
    def main_photo(self):
        photos = getattr(self, "ordered_photos", None)
        if photos is None:
            photos = list(self.photos.all())
        return photos[0] if photos else None

    @property
    def is_editable(self) -> bool:
        return not self.is_deleted and self.status != AdStatus.SOLD

    @property
    def is_checking(self) -> bool:
        return (
            self.status == AdStatus.PENDING
            and self.review_queued_at is None
            and timezone.now() - self.status_changed_at < CHECK_TIMEOUT
        )


def photo_image_path(instance, filename):
    now = timezone.now()
    return f"ads/{now:%Y/%m}/{filename}"


def photo_thumb_path(instance, filename):
    now = timezone.now()
    return f"ads/{now:%Y/%m}/thumbs/{filename}"


class AdPhoto(models.Model):
    ad = models.ForeignKey(
        Ad,
        verbose_name="объявление",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="photos",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="кто загрузил",
        on_delete=models.CASCADE,
        related_name="+",
    )
    image = models.ImageField("фото", upload_to=photo_image_path)
    thumb = models.ImageField("миниатюра", upload_to=photo_thumb_path)
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    position = models.PositiveSmallIntegerField("порядок", default=0)
    is_flagged = models.BooleanField("подозрительное", default=False)
    created_at = models.DateTimeField("загружено", auto_now_add=True)

    class Meta:
        verbose_name = "фото"
        verbose_name_plural = "фото"
        ordering = ("position", "pk")
        indexes = [models.Index(fields=["ad", "position"], name="adphoto_ad_position_idx")]

    def __str__(self):
        return self.image.name


class AdAttributeValue(AttributeValueMixin):
    ad = models.ForeignKey(
        Ad, verbose_name="объявление", on_delete=models.CASCADE, related_name="attribute_values"
    )
    attribute = models.ForeignKey(
        "catalog.Attribute",
        verbose_name="характеристика",
        on_delete=models.CASCADE,
        related_name="+",
    )

    class Meta:
        verbose_name = "характеристика"
        verbose_name_plural = "характеристики"
        ordering = ("attribute__sort_order", "attribute_id")
        constraints = [
            models.UniqueConstraint(fields=("ad", "attribute"), name="ad_value_unique_attribute")
        ]
        indexes = [models.Index(fields=["attribute", "option"], name="ad_value_filter_idx")]

    def __str__(self):
        return f"{self.attribute.name}: {self.display}"


class SurfaceState(models.TextChoices):
    PERFECT = "perfect", "Идеальное"
    MINOR = "minor", "Мелкие следы"
    SCRATCHES = "scratches", "Заметные царапины"
    DAMAGED = "damaged", "Сколы или трещины"


class PackageItem(models.TextChoices):
    BOX = "box", "Коробка"
    CHARGER = "charger", "Зарядное устройство"
    CABLE = "cable", "Кабель"
    CASE = "case", "Чехол"
    DOCUMENTS = "documents", "Документы"


class ConditionReport(models.Model):
    ad = models.OneToOneField(
        Ad, verbose_name="объявление", on_delete=models.CASCADE, related_name="condition_report"
    )
    screen_state = models.CharField("экран", max_length=10, choices=SurfaceState, blank=True)
    body_state = models.CharField("корпус", max_length=10, choices=SurfaceState, blank=True)
    battery_health = models.PositiveSmallIntegerField(
        "ёмкость аккумулятора, %", null=True, blank=True
    )
    everything_works = models.BooleanField("всё работает", default=True)
    issues = models.TextField("что не работает", max_length=1000, blank=True)
    was_repaired = models.BooleanField("был ремонт", default=False)
    repair_note = models.CharField("что ремонтировали", max_length=300, blank=True)
    is_sealed = models.BooleanField("в заводской плёнке", default=False)
    has_receipt = models.BooleanField("есть чек", default=False)
    warranty_until = models.DateField("гарантия до", null=True, blank=True)
    package = ArrayField(
        models.CharField(max_length=20, choices=PackageItem),
        verbose_name="комплект",
        default=list,
        blank=True,
    )

    class Meta:
        verbose_name = "карта состояния"
        verbose_name_plural = "карты состояния"
        constraints = [
            models.CheckConstraint(
                condition=Q(battery_health__isnull=True) | Q(battery_health__lte=100),
                name="condition_battery_percent",
            )
        ]

    def __str__(self):
        return f"Состояние: {self.ad}"

    @property
    def package_display(self) -> list[str]:
        labels = dict(PackageItem.choices)
        return [labels[item] for item in self.package if item in labels]


class PriceChange(models.Model):
    ad = models.ForeignKey(
        Ad, verbose_name="объявление", on_delete=models.CASCADE, related_name="price_changes"
    )
    old_price = models.PositiveIntegerField("было")
    new_price = models.PositiveIntegerField("стало")
    created_at = models.DateTimeField("когда", auto_now_add=True)

    class Meta:
        verbose_name = "изменение цены"
        verbose_name_plural = "история цены"
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.old_price} → {self.new_price}"


class Favorite(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="пользователь",
        on_delete=models.CASCADE,
        related_name="favorites",
    )
    ad = models.ForeignKey(
        Ad, verbose_name="объявление", on_delete=models.CASCADE, related_name="favorites"
    )
    created_at = models.DateTimeField("добавлено", auto_now_add=True)

    class Meta:
        verbose_name = "избранное"
        verbose_name_plural = "избранное"
        ordering = ("-created_at",)
        constraints = [models.UniqueConstraint(fields=("user", "ad"), name="favorite_unique")]

    def __str__(self):
        return f"{self.user} → {self.ad}"


class SavedSearch(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="пользователь",
        on_delete=models.CASCADE,
        related_name="saved_searches",
    )
    name = models.CharField("название", max_length=200)
    query_string = models.CharField("параметры", max_length=1000)
    notify = models.BooleanField("уведомлять о новых", default=True)
    last_checked_at = models.DateTimeField("проверено", default=timezone.now)
    created_at = models.DateTimeField("создано", auto_now_add=True)

    class Meta:
        verbose_name = "сохранённый поиск"
        verbose_name_plural = "сохранённые поиски"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(fields=("user", "query_string"), name="saved_search_unique")
        ]

    def __str__(self):
        return self.name


class PriceStat(models.Model):
    device_model = models.ForeignKey(
        "catalog.DeviceModel",
        verbose_name="модель",
        on_delete=models.CASCADE,
        related_name="price_stats",
    )
    condition = models.CharField("состояние", max_length=10, choices=Condition)
    price_key = models.PositiveIntegerField("ключ", default=0)
    key_option = models.ForeignKey(
        "catalog.AttributeOption",
        verbose_name="вариант",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
    )
    p25 = models.PositiveIntegerField("25-й перцентиль")
    median = models.PositiveIntegerField("медиана")
    p75 = models.PositiveIntegerField("75-й перцентиль")
    sample_size = models.PositiveIntegerField("объявлений в выборке")
    updated_at = models.DateTimeField("пересчитано", auto_now=True)

    class Meta:
        verbose_name = "статистика цен"
        verbose_name_plural = "статистика цен"
        constraints = [
            models.UniqueConstraint(
                fields=("device_model", "condition", "price_key"), name="price_stat_unique"
            )
        ]

    def __str__(self):
        return f"{self.device_model} ({self.get_condition_display()}): {self.median} ₽"
