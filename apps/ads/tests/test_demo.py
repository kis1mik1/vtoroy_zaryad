import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.accounts.models import User
from apps.ads.models import Ad

pytestmark = pytest.mark.django_db


def test_seed_demo_requires_catalog():
    with pytest.raises(CommandError, match="load_catalog"):
        call_command("seed_demo", users=2, ads=2)


def test_seed_demo_creates_data_and_clears():
    call_command("load_catalog")

    call_command("seed_demo", users=4, ads=20)

    sellers = User.objects.filter(email__endswith="@demo.vtoroy-zaryad.ru")
    assert sellers.count() == 4
    ads = Ad.objects.filter(seller__in=sellers)
    assert ads.count() == 20
    assert all(ad.price > 0 and ad.search_vector is not None for ad in ads)
    assert ads.filter(photos__isnull=False).exists()

    call_command("seed_demo", users=1, ads=1, clear=True)
    assert User.objects.filter(email__endswith="@demo.vtoroy-zaryad.ru").count() == 1
