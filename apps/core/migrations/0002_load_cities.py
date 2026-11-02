from django.db import migrations

CITIES = (
    ("Приморский край", (
        ("Владивосток", "vladivostok"),
        ("Уссурийск", "ussuriysk"),
        ("Находка", "nakhodka"),
        ("Артём", "artem"),
        ("Большой Камень", "bolshoy-kamen"),
        ("Арсеньев", "arsenyev"),
        ("Спасск-Дальний", "spassk-dalny"),
        ("Партизанск", "partizansk"),
        ("Дальнегорск", "dalnegorsk"),
        ("Лесозаводск", "lesozavodsk"),
        ("Фокино", "fokino"),
    )),
    ("Хабаровский край", (
        ("Хабаровск", "khabarovsk"),
        ("Комсомольск-на-Амуре", "komsomolsk-na-amure"),
    )),
    ("Амурская область", (("Благовещенск", "blagoveshchensk"),)),
    ("Сахалинская область", (("Южно-Сахалинск", "yuzhno-sakhalinsk"),)),
    ("Камчатский край", (("Петропавловск-Камчатский", "petropavlovsk-kamchatsky"),)),
    ("Республика Саха (Якутия)", (("Якутск", "yakutsk"),)),
    ("Магаданская область", (("Магадан", "magadan"),)),
    ("Еврейская автономная область", (("Биробиджан", "birobidzhan"),)),
)


def load_cities(apps, schema_editor):
    City = apps.get_model("core", "City")
    order = 0
    for region, cities in CITIES:
        for name, slug in cities:
            order += 10
            City.objects.update_or_create(
                slug=slug,
                defaults={
                    "name": name,
                    "region": region,
                    "sort_order": order,
                    "is_default": slug == "vladivostok",
                },
            )


def unload_cities(apps, schema_editor):
    City = apps.get_model("core", "City")
    slugs = [slug for _, cities in CITIES for _, slug in cities]
    City.objects.filter(slug__in=slugs).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]

    operations = [migrations.RunPython(load_cities, unload_cities)]
