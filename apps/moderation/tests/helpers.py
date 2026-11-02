from decimal import Decimal

from apps.accounts.tests.factories import UserFactory
from apps.ads import services
from apps.ads.services import AdDraft, AttributeValue
from apps.ads.tests.factories import make_photo
from apps.core.models import City


def submit(phones, *, seller=None, photos=1, **fields):
    seller = seller or UserFactory()
    values = {
        "category": phones["category"],
        "brand": phones["apple"],
        "device_model": phones["iphone"],
        "custom_model_name": "",
        "title": "",
        "description": "Телефон в хорошем состоянии, всё работает, батарея держит день.",
        "price": 40_000,
        "is_negotiable": False,
        "condition": "used",
        "city": City.objects.get(slug="vladivostok"),
    }
    values.update(fields)
    return services.create_ad(
        seller,
        AdDraft(
            fields=values,
            attributes=[
                AttributeValue(phones["attributes"]["storage"], option=phones["storage"]["128 ГБ"]),
                AttributeValue(phones["attributes"]["screen"], number=Decimal("6.1")),
            ],
            condition={"body_state": "minor"},
            photos=[make_photo(seller) for _ in range(photos)],
        ),
    )
