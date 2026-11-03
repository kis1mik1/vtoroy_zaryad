from django.db import migrations

TARIFFS = [
    {
        "code": "bump",
        "title": "Поднять",
        "description": "Объявление снова окажется среди новых, как будто его только что опубликовали.",
        "price": 99,
        "bump": True,
        "sort_order": 10,
    },
    {
        "code": "highlight",
        "title": "Выделить",
        "description": "Карточка с ярким контуром заметнее в поиске и ленте.",
        "price": 149,
        "highlight_days": 7,
        "sort_order": 20,
    },
    {
        "code": "pin",
        "title": "Закрепить",
        "description": "Объявление показывается первым в своём разделе и в поиске.",
        "price": 249,
        "pin_days": 3,
        "sort_order": 30,
    },
    {
        "code": "turbo",
        "title": "Турбо",
        "description": "Всё сразу и на 98 ₽ дешевле, чем по отдельности.",
        "price": 399,
        "bump": True,
        "highlight_days": 7,
        "pin_days": 3,
        "sort_order": 40,
    },
]


def load(apps, schema_editor):
    PromotionTariff = apps.get_model("payments", "PromotionTariff")
    for tariff in TARIFFS:
        PromotionTariff.objects.update_or_create(code=tariff["code"], defaults=tariff)


def unload(apps, schema_editor):
    apps.get_model("payments", "PromotionTariff").objects.filter(
        code__in=[tariff["code"] for tariff in TARIFFS], payments__isnull=True
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("payments", "0001_initial")]

    operations = [migrations.RunPython(load, unload)]
