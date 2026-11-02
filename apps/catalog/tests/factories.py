import factory

from apps.catalog.models import (
    Attribute,
    AttributeKind,
    AttributeOption,
    Brand,
    Category,
    DeviceModel,
)


class CategoryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Category

    name = factory.Sequence(lambda n: f"Категория {n}")
    slug = factory.Sequence(lambda n: f"category-{n}")
    has_battery = True
    has_screen = True


class BrandFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Brand

    name = factory.Sequence(lambda n: f"Brand{n}")
    slug = factory.Sequence(lambda n: f"brand-{n}")


class DeviceModelFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = DeviceModel

    brand = factory.SubFactory(BrandFactory)
    category = factory.SubFactory(CategoryFactory)
    name = factory.Sequence(lambda n: f"Model {n}")
    slug = factory.Sequence(lambda n: f"model-{n}")
    release_year = 2023


class AttributeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Attribute

    category = factory.SubFactory(CategoryFactory)
    code = factory.Sequence(lambda n: f"attr{n}")
    name = factory.Sequence(lambda n: f"Характеристика {n}")
    kind = AttributeKind.CHOICE


class AttributeOptionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AttributeOption

    attribute = factory.SubFactory(AttributeFactory)
    value = factory.Sequence(lambda n: f"Вариант {n}")
