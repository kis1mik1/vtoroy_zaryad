from django.contrib import admin

from .models import (
    Attribute,
    AttributeOption,
    Brand,
    Category,
    DeviceModel,
    DeviceModelOption,
    DeviceModelSpec,
)


class ChildCategoryInline(admin.TabularInline):
    model = Category
    fk_name = "parent"
    extra = 0
    fields = ("name", "slug", "sort_order", "is_active", "has_battery", "has_screen")
    prepopulated_fields = {"slug": ("name",)}
    show_change_link = True


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("__str__", "slug", "sort_order", "is_active", "has_battery", "has_screen")
    list_filter = ("parent", "is_active")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    list_select_related = ("parent",)
    inlines = [ChildCategoryInline]


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")
    search_fields = ("name", "aliases")
    prepopulated_fields = {"slug": ("name",)}
    filter_horizontal = ("categories",)


class AttributeOptionInline(admin.TabularInline):
    model = AttributeOption
    extra = 1
    fields = ("value", "sort_order")


@admin.register(Attribute)
class AttributeAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "category",
        "code",
        "kind",
        "is_variant",
        "is_required",
        "is_filterable",
        "is_price_key",
        "in_title",
    )
    list_filter = ("category", "kind", "is_variant", "is_filterable")
    search_fields = ("name", "code")
    list_select_related = ("category__parent",)
    inlines = [AttributeOptionInline]


class DeviceModelSpecInline(admin.TabularInline):
    model = DeviceModelSpec
    extra = 0
    fields = ("attribute", "option", "value_number", "value_bool")
    autocomplete_fields = ("option",)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "attribute" and request.resolver_match.kwargs.get("object_id"):
            model = DeviceModel.objects.get(pk=request.resolver_match.kwargs["object_id"])
            kwargs["queryset"] = Attribute.objects.filter(category=model.category)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class DeviceModelOptionInline(admin.TabularInline):
    model = DeviceModelOption
    extra = 0
    autocomplete_fields = ("option",)


@admin.register(AttributeOption)
class AttributeOptionAdmin(admin.ModelAdmin):
    list_display = ("value", "attribute")
    search_fields = ("value", "attribute__name", "attribute__category__name")
    list_select_related = ("attribute__category",)

    def has_module_permission(self, request):
        return False


@admin.register(DeviceModel)
class DeviceModelAdmin(admin.ModelAdmin):
    list_display = ("name", "brand", "category", "release_year", "is_active")
    list_filter = ("category", "brand", "is_active")
    search_fields = ("name", "brand__name", "aliases")
    list_select_related = ("brand", "category")
    autocomplete_fields = ("brand",)
    inlines = [DeviceModelSpecInline, DeviceModelOptionInline]
