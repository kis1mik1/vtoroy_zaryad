from decimal import Decimal

from apps.accounts.tests.factories import UserFactory
from apps.ads import services
from apps.ads.models import AdStatus
from apps.ads.services import AdDraft, AttributeValue
from apps.core.models import City

from .factories import make_photo


def publish(phones, *, seller=None, storage="128 ГБ", price=40_000, condition="used",
            city="vladivostok", description=None, model=True, custom=""):  # fmt: skip
    seller = seller or UserFactory()
    attributes = [
        AttributeValue(phones["attributes"]["storage"], option=phones["storage"][storage]),
        AttributeValue(phones["attributes"]["screen"], number=Decimal("6.1")),
    ]
    ad = services.create_ad(
        seller,
        AdDraft(
            fields={
                "category": phones["category"],
                "brand": phones["apple"],
                "device_model": phones["iphone"] if model else None,
                "custom_model_name": custom,
                "title": "",
                "description": description
                or "Телефон в хорошем состоянии, всё работает, батарея держит день.",
                "price": price,
                "is_negotiable": False,
                "condition": condition,
                "city": City.objects.get(slug=city),
            },
            attributes=attributes,
            condition={"body_state": "minor"},
            photos=[make_photo(seller)],
        ),
    )
    services.approve(ad)
    ad.refresh_from_db()
    assert ad.status == AdStatus.ACTIVE
    return ad
