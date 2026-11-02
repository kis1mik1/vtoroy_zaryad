from django.core.cache import cache

from .models import City

CITIES_CACHE_KEY = "core:cities:v1"


def get_cities() -> list[City]:
    cities = cache.get(CITIES_CACHE_KEY)
    if cities is None:
        cities = list(City.objects.all())
        cache.set(CITIES_CACHE_KEY, cities, 60 * 60 * 24)
    return cities


def get_city_by_slug(slug: str) -> City | None:
    return next((city for city in get_cities() if city.slug == slug), None)


def get_default_city() -> City | None:
    cities = get_cities()
    return next((city for city in cities if city.is_default), cities[0] if cities else None)


def get_cities_by_region() -> list[tuple[str, list[City]]]:
    regions: dict[str, list[City]] = {}
    for city in get_cities():
        regions.setdefault(city.region, []).append(city)
    return list(regions.items())


def clear_cities_cache() -> None:
    cache.delete(CITIES_CACHE_KEY)
