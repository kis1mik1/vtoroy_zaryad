import factory

from apps.core.models import City


class CityFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = City
        django_get_or_create = ("slug",)

    name = factory.Sequence(lambda n: f"Город {n}")
    slug = factory.Sequence(lambda n: f"city-{n}")
    region = "Тестовый край"
    sort_order = factory.Sequence(lambda n: 1000 + n)
