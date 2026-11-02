import re
from decimal import Decimal

from django import forms
from django.utils import timezone

from apps.catalog.models import AttributeKind, Brand, Category, DeviceModel
from apps.catalog.selectors import attributes_for, brands_for
from apps.core.forms import CityChoiceField

from .models import MAX_PRICE, Ad, Condition, ConditionReport, PackageItem, SurfaceState
from .services import AttributeValue

OTHER_MODEL = "other"
BOOL_CHOICES = [("", "Не указано"), ("yes", "Да"), ("no", "Нет")]


class PriceField(forms.IntegerField):
    def to_python(self, value):
        if isinstance(value, str):
            value = re.sub(r"[\s  ₽]", "", value)
        return super().to_python(value)


class AdForm(forms.ModelForm):
    category = forms.ModelChoiceField(
        label="Категория",
        queryset=Category.objects.filter(is_active=True, children__isnull=True),
        widget=forms.RadioSelect,
        error_messages={"required": "Выберите категорию.", "invalid_choice": "Выберите категорию."},
    )
    brand = forms.ModelChoiceField(label="Бренд", queryset=Brand.objects.all(), required=False)
    device_model = forms.CharField(label="Модель", required=False)
    price = PriceField(
        label="Цена, ₽",
        min_value=1,
        max_value=MAX_PRICE,
        widget=forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "off"}),
        error_messages={"min_value": "Укажите цену больше нуля."},
    )
    city = CityChoiceField()

    class Meta:
        model = Ad
        fields = (
            "custom_model_name",
            "title",
            "description",
            "price",
            "is_negotiable",
            "condition",
            "city",
        )
        labels = {
            "custom_model_name": "Модель или название товара",
            "title": "Название объявления",
            "description": "Описание",
            "is_negotiable": "Торг уместен",
            "condition": "Состояние",
        }
        help_texts = {
            "title": "Можно не заполнять: соберём из модели и характеристик.",
            "description": "Расскажите, сколько пользовались, почему продаёте, что в комплекте. "
            "Телефон и ссылки не указывайте.",
        }
        widgets = {
            "title": forms.TextInput(attrs={"maxlength": 120}),
            "description": forms.Textarea(attrs={"rows": 6, "maxlength": 5000}),
            "condition": forms.RadioSelect,
            "custom_model_name": forms.TextInput(attrs={"maxlength": 120}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["title"].required = False
        self.fields["condition"].choices = Condition.choices
        if self.instance.pk:
            self.initial.update(
                category=self.instance.category_id,
                brand=self.instance.brand_id,
                device_model=self.instance.device_model_id or OTHER_MODEL,
            )

    def clean_description(self):
        description = self.cleaned_data["description"].strip()
        if len(description) < 20:
            raise forms.ValidationError("Опишите товар подробнее — хотя бы пару предложений.")
        return description

    def clean(self):
        cleaned = super().clean()
        category = cleaned.get("category")
        if category is None:
            return cleaned

        brand = cleaned.get("brand")
        if brand is not None and not brands_for(category).filter(pk=brand.pk).exists():
            self.add_error("brand", "Этот бренд не относится к выбранной категории.")
            return cleaned

        value = cleaned.get("device_model") or ""
        model = None
        if value and value != OTHER_MODEL:
            model = (
                DeviceModel.objects.filter(
                    pk=value if value.isdigit() else None, category=category, is_active=True
                )
                .select_related("brand")
                .first()
            )
            if model is None or (brand is not None and model.brand_id != brand.pk):
                self.add_error("device_model", "Выберите модель из списка.")
                return cleaned
            cleaned["brand"] = model.brand
        elif not cleaned.get("custom_model_name", "").strip():
            self.add_error(
                "custom_model_name",
                "Укажите модель или название товара.",
            )
        cleaned["device_model"] = model
        if model is not None:
            cleaned["custom_model_name"] = ""
        return cleaned

    def ad_fields(self) -> dict:
        data = self.cleaned_data
        return {
            "category": data["category"],
            "brand": data.get("brand"),
            "device_model": data.get("device_model"),
            "custom_model_name": data.get("custom_model_name", "").strip(),
            "title": data.get("title", "").strip(),
            "description": data["description"],
            "price": data["price"],
            "is_negotiable": data["is_negotiable"],
            "condition": data["condition"],
            "city": data["city"],
        }


class AttributesForm(forms.Form):
    prefix_name = "attr_"

    def __init__(self, category, device_model=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.category = category
        self.device_model = device_model
        self.attributes = attributes_for(category) if category else []
        specs = (
            {spec.attribute_id: spec for spec in device_model.specs.all()} if device_model else {}
        )
        allowed = {}
        if device_model:
            for item in device_model.allowed_options.all():
                allowed.setdefault(item.option.attribute_id, set()).add(item.option_id)

        self.fixed = []
        for attribute in self.attributes:
            spec = specs.get(attribute.pk)
            if spec is not None and not attribute.is_variant:
                self.fixed.append(
                    AttributeValue(attribute, spec.option, spec.value_number, spec.value_bool)
                )
                continue
            only = allowed.get(attribute.pk, set())
            if attribute.is_variant and len(only) == 1:
                option = next(o for o in attribute.options.all() if o.pk in only)
                self.fixed.append(AttributeValue(attribute, option=option))
                continue
            self.fields[self.field_name(attribute)] = self._field(
                attribute, allowed.get(attribute.pk)
            )

    @classmethod
    def field_name(cls, attribute) -> str:
        return f"{cls.prefix_name}{attribute.code}"

    def _field(self, attribute, allowed_ids):
        common = {"label": attribute.name, "required": attribute.is_required}
        if attribute.kind == AttributeKind.CHOICE:
            options = [o for o in attribute.options.all() if not allowed_ids or o.pk in allowed_ids]
            choices = [(str(o.pk), o.value) for o in options]
            if len(choices) == 1 and attribute.is_required:
                field = forms.ChoiceField(choices=choices, **common)
                field.initial = choices[0][0]
            else:
                field = forms.ChoiceField(choices=[("", "Не выбрано"), *choices], **common)
            field.option_map = {str(o.pk): o for o in options}
            return field
        if attribute.kind == AttributeKind.NUMBER:
            label = f"{attribute.name}, {attribute.unit}" if attribute.unit else attribute.name
            return forms.DecimalField(
                label=label,
                required=attribute.is_required,
                min_value=Decimal("0.01"),
                max_digits=12,
                decimal_places=2,
                localize=True,
                widget=forms.TextInput(attrs={"inputmode": "decimal"}),
            )
        return forms.ChoiceField(
            choices=BOOL_CHOICES, widget=forms.RadioSelect, initial="", **common
        )

    def values(self) -> list[AttributeValue]:
        values = list(self.fixed)
        for attribute in self.attributes:
            name = self.field_name(attribute)
            if name not in self.fields:
                continue
            raw = self.cleaned_data.get(name)
            if raw in (None, ""):
                continue
            if attribute.kind == AttributeKind.CHOICE:
                values.append(AttributeValue(attribute, option=self.fields[name].option_map[raw]))
            elif attribute.kind == AttributeKind.NUMBER:
                values.append(AttributeValue(attribute, number=raw))
            else:
                values.append(AttributeValue(attribute, flag=raw == "yes"))
        return values

    @classmethod
    def initial_from_ad(cls, ad) -> dict:
        initial = {}
        for value in ad.attribute_values.select_related("attribute"):
            name = cls.field_name(value.attribute)
            if value.option_id:
                initial[name] = str(value.option_id)
            elif value.value_number is not None:
                initial[name] = value.value_number
            elif value.value_bool is not None:
                initial[name] = "yes" if value.value_bool else "no"
        return initial


class ConditionForm(forms.ModelForm):
    package = forms.MultipleChoiceField(
        label="Комплект",
        choices=PackageItem.choices,
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    USED_FIELDS = (
        "screen_state",
        "body_state",
        "battery_health",
        "everything_works",
        "issues",
        "was_repaired",
        "repair_note",
    )
    NEW_FIELDS = ("is_sealed", "has_receipt", "warranty_until")

    class Meta:
        model = ConditionReport
        fields = (
            "screen_state",
            "body_state",
            "battery_health",
            "everything_works",
            "issues",
            "was_repaired",
            "repair_note",
            "is_sealed",
            "has_receipt",
            "warranty_until",
            "package",
        )
        labels = {
            "screen_state": "Экран",
            "body_state": "Корпус",
            "battery_health": "Ёмкость аккумулятора, %",
            "everything_works": "Всё работает исправно",
            "issues": "Что не работает или работает плохо",
            "was_repaired": "Был ремонт или замена деталей",
            "repair_note": "Что ремонтировали или меняли",
            "is_sealed": "В заводской плёнке, не активирован",
            "has_receipt": "Есть чек",
            "warranty_until": "Гарантия до",
        }
        help_texts = {
            "battery_health": "На iPhone: Настройки → Аккумулятор → Состояние.",
        }
        widgets = {
            "screen_state": forms.RadioSelect,
            "body_state": forms.RadioSelect,
            "battery_health": forms.NumberInput(attrs={"min": 1, "max": 100}),
            "issues": forms.Textarea(attrs={"rows": 3}),
            "warranty_until": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }

    def __init__(self, *args, condition=None, category=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.condition = condition
        self.category = category
        self.fields["screen_state"].choices = SurfaceState.choices
        self.fields["body_state"].choices = SurfaceState.choices
        if category is not None and not category.has_screen:
            del self.fields["screen_state"]
        if category is not None and not category.has_battery:
            del self.fields["battery_health"]

    def clean_battery_health(self):
        value = self.cleaned_data.get("battery_health")
        if value is not None and not 1 <= value <= 100:
            raise forms.ValidationError("Укажите число от 1 до 100.")
        return value

    def clean_warranty_until(self):
        value = self.cleaned_data.get("warranty_until")
        if value and value < timezone.localdate():
            raise forms.ValidationError("Дата окончания гарантии уже прошла.")
        return value

    def clean(self):
        cleaned = super().clean()
        if self.condition == Condition.USED:
            if "screen_state" in self.fields and not cleaned.get("screen_state"):
                self.add_error("screen_state", "Опишите состояние экрана.")
            if not cleaned.get("body_state"):
                self.add_error("body_state", "Опишите состояние корпуса.")
            if not cleaned.get("everything_works") and not cleaned.get("issues", "").strip():
                self.add_error("issues", "Расскажите, что именно не работает.")
            if cleaned.get("was_repaired") and not cleaned.get("repair_note", "").strip():
                self.add_error("repair_note", "Укажите, что ремонтировали.")
        return cleaned

    def report_data(self) -> dict:
        data = self.cleaned_data
        report = {
            "package": data.get("package", []),
            "screen_state": "",
            "body_state": "",
            "battery_health": None,
            "everything_works": True,
            "issues": "",
            "was_repaired": False,
            "repair_note": "",
            "is_sealed": False,
            "has_receipt": False,
            "warranty_until": None,
        }
        fields = self.USED_FIELDS if self.condition == Condition.USED else self.NEW_FIELDS
        for name in fields:
            if name in data:
                report[name] = data[name]
        if report["everything_works"]:
            report["issues"] = ""
        if not report["was_repaired"]:
            report["repair_note"] = ""
        return report
