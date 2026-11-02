from django.db import migrations

NAMES = {
    "vladivostok": "во Владивостоке",
    "ussuriysk": "в Уссурийске",
    "nakhodka": "в Находке",
    "artem": "в Артёме",
    "bolshoy-kamen": "в Большом Камне",
    "arsenyev": "в Арсеньеве",
    "spassk-dalny": "в Спасске-Дальнем",
    "partizansk": "в Партизанске",
    "dalnegorsk": "в Дальнегорске",
    "lesozavodsk": "в Лесозаводске",
    "fokino": "в Фокино",
    "khabarovsk": "в Хабаровске",
    "komsomolsk-na-amure": "в Комсомольске-на-Амуре",
    "blagoveshchensk": "в Благовещенске",
    "yuzhno-sakhalinsk": "в Южно-Сахалинске",
    "petropavlovsk-kamchatsky": "в Петропавловске-Камчатском",
    "yakutsk": "в Якутске",
    "magadan": "в Магадане",
    "birobidzhan": "в Биробиджане",
}


def fill(apps, schema_editor):
    City = apps.get_model("core", "City")
    for slug, name_in in NAMES.items():
        City.objects.filter(slug=slug).update(name_in=name_in)


class Migration(migrations.Migration):
    dependencies = [("core", "0003_city_name_in")]

    operations = [migrations.RunPython(fill, migrations.RunPython.noop)]
