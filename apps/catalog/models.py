from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class Category(models.Model):
    parent = models.ForeignKey(
        "self",
        verbose_name="родительская категория",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="children",
    )
    name = models.CharField("название", max_length=100)
    slug = models.SlugField("адрес в ссылке", max_length=100, unique=True)
    icon = models.CharField("иконка", max_length=40, blank=True)
    seo_description = models.CharField("описание для поисковиков", max_length=300, blank=True)
    sort_order = models.PositiveSmallIntegerField("порядок", default=0)
    is_active = models.BooleanField("активна", default=True)
    has_battery = models.BooleanField("есть аккумулятор", default=False)
    has_screen = models.BooleanField("есть экран", default=False)

    class Meta:
        verbose_name = "категория"
        verbose_name_plural = "категории"
        ordering = ("sort_order", "name")

    def __str__(self):
        return f"{self.parent.name} → {self.name}" if self.parent_id else self.name

    def clean(self):
        if self.parent_id and self.parent.parent_id:
            raise ValidationError({"parent": "Дерево категорий может быть только двухуровневым."})
        if self.parent_id and self.parent_id == self.pk:
            raise ValidationError({"parent": "Категория не может быть родителем самой себя."})


class Brand(models.Model):
    name = models.CharField("название", max_length=100, unique=True)
    slug = models.SlugField("адрес в ссылке", max_length=100, unique=True)
    categories = models.ManyToManyField(Category, verbose_name="категории", related_name="brands")
    aliases = ArrayField(
        models.CharField(max_length=100),
        verbose_name="другие написания",
        default=list,
        blank=True,
        help_text="Через запятую: «эпл», «самсунг».",
    )

    class Meta:
        verbose_name = "бренд"
        verbose_name_plural = "бренды"
        ordering = ("name",)

    def __str__(self):
        return self.name


class DeviceModel(models.Model):
    brand = models.ForeignKey(
        Brand, verbose_name="бренд", on_delete=models.PROTECT, related_name="device_models"
    )
    category = models.ForeignKey(
        Category, verbose_name="категория", on_delete=models.PROTECT, related_name="device_models"
    )
    name = models.CharField("название", max_length=150)
    slug = models.SlugField("адрес в ссылке", max_length=200, unique=True)
    release_year = models.PositiveSmallIntegerField("год выхода", null=True, blank=True)
    aliases = ArrayField(
        models.CharField(max_length=100),
        verbose_name="другие написания",
        default=list,
        blank=True,
    )
    is_active = models.BooleanField("активна", default=True)

    class Meta:
        verbose_name = "модель устройства"
        verbose_name_plural = "модели устройств"
        ordering = ("brand__name", "-release_year", "name")
        constraints = [
            models.UniqueConstraint(
                fields=("brand", "category", "name"), name="device_model_unique_name"
            )
        ]

    def __str__(self):
        return self.full_name

    @property
    def full_name(self) -> str:
        if self.name.lower().startswith(self.brand.name.lower()):
            return self.name
        return f"{self.brand.name} {self.name}"


class AttributeKind(models.TextChoices):
    CHOICE = "choice", "Выбор из списка"
    NUMBER = "number", "Число"
    BOOLEAN = "boolean", "Да или нет"


class FilterWidget(models.TextChoices):
    CHECKBOXES = "checkboxes", "Флажки"
    RANGE = "range", "Диапазон"
    TOGGLE = "toggle", "Да/нет"


class Attribute(models.Model):
    category = models.ForeignKey(
        Category, verbose_name="категория", on_delete=models.CASCADE, related_name="attributes"
    )
    code = models.SlugField("код", max_length=50)
    name = models.CharField("название", max_length=100)
    kind = models.CharField("тип", max_length=10, choices=AttributeKind)
    unit = models.CharField("единица", max_length=20, blank=True)
    is_required = models.BooleanField("обязательная", default=False)
    is_variant = models.BooleanField(
        "выбирает продавец",
        default=False,
        help_text="Например, память или цвет. Остальное подставляется из справочника модели.",
    )
    is_filterable = models.BooleanField("в фильтрах", default=False)
    is_price_key = models.BooleanField("влияет на цену", default=False)
    in_title = models.BooleanField("в названии объявления", default=False)
    filter_widget = models.CharField(
        "вид фильтра", max_length=12, choices=FilterWidget, default=FilterWidget.CHECKBOXES
    )
    sort_order = models.PositiveSmallIntegerField("порядок", default=0)

    class Meta:
        verbose_name = "характеристика"
        verbose_name_plural = "характеристики"
        ordering = ("category", "sort_order", "pk")
        constraints = [
            models.UniqueConstraint(fields=("category", "code"), name="attribute_unique_code")
        ]

    def __str__(self):
        return f"{self.category.name}: {self.name}"

    def format_number(self, value) -> str:
        text = f"{value.normalize():f}" if hasattr(value, "normalize") else str(value)
        text = text.replace(".", ",")
        if not self.unit:
            return text
        separator = "" if self.unit in ("″", "%") else "\u00a0"
        return f"{text}{separator}{self.unit}"


class AttributeOption(models.Model):
    attribute = models.ForeignKey(
        Attribute, verbose_name="характеристика", on_delete=models.CASCADE, related_name="options"
    )
    value = models.CharField("значение", max_length=100)
    sort_order = models.PositiveSmallIntegerField("порядок", default=0)

    class Meta:
        verbose_name = "вариант значения"
        verbose_name_plural = "варианты значений"
        ordering = ("attribute", "sort_order", "pk")
        constraints = [
            models.UniqueConstraint(fields=("attribute", "value"), name="option_unique_value")
        ]

    def __str__(self):
        return self.value


class AttributeValueMixin(models.Model):
    option = models.ForeignKey(
        AttributeOption, verbose_name="вариант", on_delete=models.PROTECT, null=True, blank=True
    )
    value_number = models.DecimalField(
        "число", max_digits=12, decimal_places=2, null=True, blank=True
    )
    value_bool = models.BooleanField("да/нет", null=True, blank=True)

    class Meta:
        abstract = True

    @property
    def display(self) -> str:
        if self.option_id:
            return self.option.value
        if self.value_number is not None:
            return self.attribute.format_number(self.value_number)
        if self.value_bool is not None:
            return "есть" if self.value_bool else "нет"
        return ""


class DeviceModelSpec(AttributeValueMixin):
    device_model = models.ForeignKey(
        DeviceModel, verbose_name="модель", on_delete=models.CASCADE, related_name="specs"
    )
    attribute = models.ForeignKey(
        Attribute, verbose_name="характеристика", on_delete=models.CASCADE, related_name="+"
    )

    class Meta:
        verbose_name = "характеристика модели"
        verbose_name_plural = "характеристики модели"
        constraints = [
            models.UniqueConstraint(
                fields=("device_model", "attribute"), name="device_spec_unique_attribute"
            ),
            models.CheckConstraint(
                condition=Q(option__isnull=False)
                | Q(value_number__isnull=False)
                | Q(value_bool__isnull=False),
                name="device_spec_has_value",
            ),
        ]

    def __str__(self):
        return f"{self.attribute.name}: {self.display}"


class DeviceModelOption(models.Model):
    device_model = models.ForeignKey(
        DeviceModel, verbose_name="модель", on_delete=models.CASCADE, related_name="allowed_options"
    )
    option = models.ForeignKey(
        AttributeOption, verbose_name="вариант", on_delete=models.CASCADE, related_name="+"
    )

    class Meta:
        verbose_name = "допустимый вариант"
        verbose_name_plural = "допустимые варианты"
        constraints = [
            models.UniqueConstraint(fields=("device_model", "option"), name="device_option_unique")
        ]

    def __str__(self):
        return f"{self.option.attribute.name}: {self.option.value}"
