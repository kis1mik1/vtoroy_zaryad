from decimal import Decimal
from urllib.parse import urlencode

from django import forms
from django.db.models import Q

from apps.catalog.models import AttributeKind, Brand, DeviceModel
from apps.catalog.selectors import attributes_for
from apps.core.selectors import get_city_by_slug

from .models import MAX_PRICE, AdAttributeValue, Condition
from .search import apply_query
from .selectors import SORTS

ALL_CITIES = "all"
PAGE_PARAM = "page"


class SearchForm(forms.Form):
    q = forms.CharField(label="Что ищете", required=False, max_length=100)
    city = forms.CharField(required=False)
    price_min = forms.IntegerField(label="от", required=False, min_value=0, max_value=MAX_PRICE)
    price_max = forms.IntegerField(label="до", required=False, min_value=0, max_value=MAX_PRICE)
    condition = forms.ChoiceField(
        label="Состояние",
        required=False,
        choices=[("", "Любое"), *Condition.choices],
        widget=forms.RadioSelect,
    )
    brand = forms.MultipleChoiceField(
        label="Бренд", required=False, widget=forms.CheckboxSelectMultiple
    )
    model = forms.ChoiceField(label="Модель", required=False)
    with_photo = forms.BooleanField(label="Только с фото", required=False)
    sort = forms.ChoiceField(
        label="Сортировка",
        required=False,
        choices=[(key, label) for key, (label, _) in SORTS.items()],
    )

    def __init__(self, data, *, category=None, default_city=None):
        super().__init__(data)
        self.category = category
        self.default_city = default_city
        self.attribute_fields = []
        self.is_leaf = category is not None and not category.children.exists()

        brands = Brand.objects.filter(
            Q(categories=category) | Q(categories__parent=category)
            if category
            else Q(device_models__isnull=False)
        ).distinct()
        self.fields["brand"].choices = [(b.slug, b.name) for b in brands.order_by("name")]

        selected = data.getlist("brand") if hasattr(data, "getlist") else []
        models = DeviceModel.objects.none()
        if self.is_leaf and len(selected) == 1:
            models = DeviceModel.objects.filter(
                category=category, brand__slug=selected[0], is_active=True
            ).order_by("-release_year", "name")
        self.fields["model"].choices = [("", "Любая")] + [(m.slug, m.name) for m in models]

        if self.is_leaf:
            for attribute in attributes_for(category):
                if attribute.is_filterable:
                    self._add_attribute_field(attribute)

    def _add_attribute_field(self, attribute):
        name = f"a_{attribute.code}"
        if attribute.kind == AttributeKind.CHOICE:
            self.fields[name] = forms.MultipleChoiceField(
                label=attribute.name,
                required=False,
                choices=[(str(o.pk), o.value) for o in attribute.options.all()],
                widget=forms.CheckboxSelectMultiple,
            )
            self.attribute_fields.append((attribute, [name]))
        elif attribute.kind == AttributeKind.NUMBER:
            for suffix, label in (("min", "от"), ("max", "до")):
                self.fields[f"{name}_{suffix}"] = forms.DecimalField(
                    label=label, required=False, min_value=0, localize=True
                )
            self.attribute_fields.append((attribute, [f"{name}_min", f"{name}_max"]))
        else:
            self.fields[name] = forms.BooleanField(label=attribute.name, required=False)
            self.attribute_fields.append((attribute, [name]))

    def city_value(self):
        raw = self.cleaned_data.get("city") if self.is_bound and self.is_valid() else ""
        if raw == ALL_CITIES:
            return None
        if raw:
            return get_city_by_slug(raw)
        return self.default_city

    def filter(self, queryset):
        data = self.cleaned_data
        city = self.city_value()
        if city is not None:
            queryset = queryset.filter(city=city)
        if self.category is not None:
            queryset = queryset.filter(
                Q(category=self.category) | Q(category__parent=self.category)
            )
        if data.get("price_min") is not None:
            queryset = queryset.filter(price__gte=data["price_min"])
        if data.get("price_max") is not None:
            queryset = queryset.filter(price__lte=data["price_max"])
        if data.get("condition"):
            queryset = queryset.filter(condition=data["condition"])
        if data.get("brand"):
            queryset = queryset.filter(
                Q(device_model__brand__slug__in=data["brand"]) | Q(brand__slug__in=data["brand"])
            )
        if data.get("model"):
            queryset = queryset.filter(device_model__slug=data["model"])
        if data.get("with_photo"):
            queryset = queryset.filter(photos__isnull=False).distinct()
        for attribute, names in self.attribute_fields:
            queryset = self._filter_attribute(queryset, attribute, names)
        return apply_query(queryset, data.get("q", ""))

    def _filter_attribute(self, queryset, attribute, names):
        data = self.cleaned_data
        values = AdAttributeValue.objects.filter(attribute=attribute)
        if attribute.kind == AttributeKind.CHOICE:
            chosen = data.get(names[0])
            if not chosen:
                return queryset
            values = values.filter(option_id__in=chosen)
        elif attribute.kind == AttributeKind.NUMBER:
            low, high = data.get(names[0]), data.get(names[1])
            if low is None and high is None:
                return queryset
            if low is not None:
                values = values.filter(value_number__gte=low)
            if high is not None:
                values = values.filter(value_number__lte=high)
        else:
            if not data.get(names[0]):
                return queryset
            values = values.filter(value_bool=True)
        return queryset.filter(pk__in=values.values("ad_id"))

    @property
    def sort_key(self) -> str:
        return self.cleaned_data.get("sort") or "date"

    def canonical_params(self) -> dict:
        params = {}
        for name, value in self.cleaned_data.items():
            if value in (None, "", [], False) or (name == "sort" and value == "date"):
                continue
            if isinstance(value, list):
                params[name] = sorted(value)
            elif isinstance(value, Decimal):
                params[name] = format(value.normalize(), "f")
            elif value is True:
                params[name] = "1"
            else:
                params[name] = str(value).strip()
        return dict(sorted(params.items()))

    def query_string(self) -> str:
        return urlencode(self.canonical_params(), doseq=True)

    def saved_key(self, path: str) -> str:
        params = self.canonical_params()
        if "city" not in params:
            params["city"] = self.default_city.slug if self.default_city else ALL_CITIES
        return f"{path}?{urlencode(dict(sorted(params.items())), doseq=True)}"

    def active_filters_count(self) -> int:
        ignored = {"q", "sort", "city"}
        return sum(1 for name in self.canonical_params() if name not in ignored)

    def describe(self) -> str:
        data = self.cleaned_data
        parts = []
        if data.get("q"):
            parts.append(f"«{data['q'].strip()}»")
        if self.category is not None:
            parts.append(self.category.name)
        city = self.city_value()
        parts.append(city.name if city else "все города")
        if data.get("price_min") is not None:
            parts.append(f"от {data['price_min']:,} ₽".replace(",", " "))
        if data.get("price_max") is not None:
            parts.append(f"до {data['price_max']:,} ₽".replace(",", " "))
        if data.get("condition"):
            parts.append(Condition(data["condition"]).label.lower())
        return " · ".join(parts)[:200]
