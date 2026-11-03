import random
import secrets
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from PIL import Image

from apps.accounts.models import ContactMode, User
from apps.catalog.models import AttributeKind, Category, DeviceModel
from apps.chat.models import Conversation, Message
from apps.core.images import fit_within, to_webp
from apps.core.models import City
from apps.moderation import services as moderation
from apps.moderation.models import ComplaintReason
from apps.reviews.models import AuthorRole, Review
from apps.reviews.services import recalculate_rating

from .market import recalculate_price_stats
from .models import Ad, AdPhoto, AdStatus, Condition, Favorite, PriceChange
from .photos import IMAGE_SIZE, THUMB_SIZE
from .search import index_ad
from .services import AdDraft, AttributeValue, create_ad

DEMO_DOMAIN = "demo.vtoroy-zaryad.ru"
PHOTOS_DIR = Path(settings.BASE_DIR) / "seed" / "photos"

FIRST_NAMES = (
    "Алексей", "Мария", "Дмитрий", "Анна", "Сергей", "Екатерина", "Иван", "Ольга", "Никита",
    "Татьяна", "Андрей", "Юлия", "Максим", "Наталья", "Артём", "Ксения", "Павел", "Дарья",
    "Роман", "Виктория", "Егор", "Алина", "Кирилл", "Светлана", "Владимир", "Полина", "Олег",
    "Елена", "Григорий", "Софья",
)  # fmt: skip
CITY_WEIGHTS = {
    "vladivostok": 14, "ussuriysk": 3, "nakhodka": 2, "artem": 2, "khabarovsk": 4,
    "blagoveshchensk": 1, "yuzhno-sakhalinsk": 1, "petropavlovsk-kamchatsky": 1, "yakutsk": 1,
}  # fmt: skip

CATEGORY_WEIGHTS = {
    "smartphones": 40, "laptops": 14, "tablets": 9, "headphones": 9, "consoles": 8,
    "gaming-accessories": 4, "wearables": 6, "cameras": 4, "gpus": 6, "speakers": 3,
}  # fmt: skip

BASE_PRICE = {
    "smartphones": {"Apple": 90000, "Samsung": 70000, "Google": 70000, "Xiaomi": 35000,
                    "Honor": 35000, "Huawei": 45000, "realme": 25000, "OnePlus": 55000,
                    "Nothing": 40000, "Tecno": 15000, "Infinix": 14000},
    "laptops": {"Apple": 140000, "default": 80000},
    "tablets": {"Apple": 80000, "Samsung": 50000, "default": 28000},
    "headphones": {"Apple": 22000, "Sony": 25000, "Bose": 30000, "default": 9000},
    "consoles": {"Sony": 55000, "Microsoft": 45000, "Nintendo": 32000, "Valve": 55000,
                 "ASUS": 70000},
    "gaming-accessories": {"default": 7000},
    "wearables": {"Apple": 40000, "Samsung": 25000, "Garmin": 45000, "default": 6000},
    "cameras": {"default": 120000},
    "gpus": {"NVIDIA": 55000, "AMD": 55000, "Intel": 25000},
    "speakers": {"default": 12000},
}  # fmt: skip
DEPRECIATION = {
    "smartphones": 0.8, "tablets": 0.84, "laptops": 0.86, "wearables": 0.8, "gpus": 0.92,
}  # fmt: skip
CPU_TIERS = (("9", 1.6), ("7", 1.25), ("5", 1.0), ("3", 0.75), ("Celeron", 0.6), ("Pentium", 0.6))
POOL_SIZE = {"smartphones": 10}
TIER_PREFIXES = {
    "galaxy a": 0.42,
    "redmi": 0.55,
    "poco": 0.75,
    "iphone se": 0.6,
    "smart band": 0.6,
    "band": 0.6,
    "redmi watch": 0.5,
    "nord": 0.75,
}
TIER_WORDS = {
    "ultra": 1.45, "max": 1.35, "pro": 1.25, "plus": 1.1, "+": 1.1, "fold": 1.9, "flip": 1.3,
    "duo": 2.2, "mini": 0.85, "lite": 0.7, "fe": 0.75, "se": 0.7, "slim": 1.0, "digital": 0.85,
    "4090": 3.2, "5090": 4.0, "4080": 2.2, "5080": 2.4, "3090": 1.6, "4070": 1.3, "5070": 1.3,
    "7800": 1.15, "7700": 0.9, "7600": 0.6, "6800": 0.9, "6700": 0.7, "6600": 0.5,
    "4060": 0.75, "3060": 0.55, "3050": 0.4, "1650": 0.22, "7900": 1.6, "9070": 1.3, "580": 0.2,
}  # fmt: skip

OPENINGS_USED = (
    "Продаю, потому что перешёл на новую модель.",
    "Освободился после обновления, лежит без дела.",
    "Подарили новый, этот больше не нужен.",
    "Продаю в связи с переездом.",
    "Покупал для работы, задачи сменились — продаю.",
)
USAGE = (
    "Пользовался около {months} мес., аккуратно.",
    "В использовании {months} мес., всегда в чехле.",
    "Был у меня {months} мес., падений не было.",
    "Пользовалась {months} мес., без ремонтов.",
)
DETAILS_USED = (
    "Мелкие потёртости видно только на свету, на фото их можно рассмотреть.",
    "Экран без царапин, стекло наклеено с первого дня.",
    "Все функции работают, могу показать при встрече.",
    "Отвязан от аккаунта, сброшен до заводских настроек.",
    "Батарея держит день при обычном использовании.",
)
OPENINGS_NEW = (
    "Новый, не активирован, в заводской плёнке.",
    "Новый, коробку вскрывал только для проверки.",
    "Выиграл в розыгрыше, мне не нужен — продаю новым.",
)
CLOSINGS = (
    "Встреча во Владивостоке в центре или у ТЦ «Калина Молл».",
    "Можно проверить на месте, торг у вещи.",
    "Отвечаю в сообщениях быстрее, чем по телефону.",
    "Без предоплаты, только личная встреча.",
    "Отправлю фото дополнительно по запросу.",
)


PROBLEM_ADS = (
    (
        "smartphones",
        "iPhone 13",
        "Продаю айфон, всё работает, батарея 86%. Звоните +7 914 123-45-67 "
        "или пишите в телеграм @iphone_vl, отвечу быстрее.",
        38000,
    ),
    (
        "smartphones",
        "",
        "Кроссовки почти новые, размер 42, надевал пару раз. Отдам с коробкой.",
        6500,
    ),
    (
        "laptops",
        "MacBook Air 13 M2",
        "Новый, не вскрывался. Только предоплата 100% на карту, отправлю после оплаты. "
        "Торга нет, на звонки не отвечаю.",
        24000,
    ),
    (
        "smartphones",
        "Galaxy S23",
        "Телефон на запчасти, заблокирован по IMEI, экран целый. Забирать в Артёме.",
        5000,
    ),
)
CUSTOM_PROBLEM_TITLE = "Кроссовки Nike Air Max, 42 размер"
COMPLAINT_COMMENTS = {
    ComplaintReason.FRAUD: "Просит предоплату на карту, на встречу не соглашается.",
    ComplaintReason.WRONG_PRICE: "В переписке называет цену на 10 тысяч больше.",
    ComplaintReason.SOLD: "Продавец написал, что уже продал, а объявление висит.",
    ComplaintReason.SPAM: "Такое же объявление уже было у этого продавца.",
    ComplaintReason.OTHER: "Фото явно из интернета, свои показать отказался.",
}

DEAL_DIALOGS = (
    ("Здравствуйте! Ещё продаёте?", "Да, в наличии. Можно посмотреть в любой день после шести."),
    ("Добрый день. Торг возможен?", "Немного уступлю при встрече, если всё устроит."),
    ("Аккумулятор менялся?", "Нет, родной. Ёмкость указал в объявлении."),
    ("Комплект полный?", "Да, коробка, кабель и документы."),
    ("Можно проверить на месте?", "Конечно, приходите, всё покажу."),
)
BUYER_REVIEWS = {
    5: (
        "Всё как в описании, встретились без опозданий.",
        "Продавец всё показал, проверили на месте. Рекомендую.",
        "Быстро договорились, техника в отличном состоянии.",
        "Честное описание и адекватная цена. Спасибо!",
    ),
    4: (
        "Всё хорошо, но на встрече пришлось подождать минут двадцать.",
        "Товар в порядке, есть мелкие царапины, о которых не сказали заранее.",
    ),
    3: ("Состояние хуже, чем на фото, но цену немного снизили.",),
    2: ("Долго отвечал и дважды переносил встречу.",),
}
SELLER_REVIEWS = (
    "Пришёл вовремя, всё проверил и сразу купил.",
    "Вежливый покупатель, сделка прошла быстро.",
)
REPLIES = ("Спасибо, пользуйтесь на здоровье!", "Спасибо за отзыв!", "Рад, что всё понравилось.")
RATING_WEIGHTS = {5: 12, 4: 5, 3: 2, 2: 1}


@dataclass
class PreparedPhoto:
    image: bytes
    thumb: bytes
    width: int
    height: int


def _prepare_photos(rng) -> dict[str, list[PreparedPhoto]]:
    prepared = {}
    for folder in sorted(PHOTOS_DIR.iterdir()) if PHOTOS_DIR.exists() else []:
        items = []
        for path in sorted(folder.glob("*.jpg")):
            with Image.open(path) as source:
                large = fit_within(source.convert("RGB"), IMAGE_SIZE)
                thumb = fit_within(source.convert("RGB"), THUMB_SIZE)
                items.append(
                    PreparedPhoto(
                        to_webp(large).read(), to_webp(thumb, quality=78).read(), *large.size
                    )
                )
        if items:
            prepared[folder.name] = items
    return prepared


def _price(rng, model: DeviceModel, condition: str, attributes) -> int:
    table = BASE_PRICE.get(model.category.slug, {})
    base = table.get(model.brand.name, table.get("default", 20000))
    name = model.name.lower().replace("+", " + ")
    for prefix, factor in TIER_PREFIXES.items():
        if name.startswith(prefix):
            base *= factor
            break
    for word, factor in TIER_WORDS.items():
        if word in name.split() or (word.isdigit() and word in name):
            base *= factor
    for value in attributes:
        if value.option is None:
            continue
        text = value.option.value
        code = value.attribute.code
        if code == "cpu" and not text.startswith("Apple"):
            base *= next((factor for key, factor in CPU_TIERS if key in text.split()[-1]), 1.0)
        elif code == "gpu" and "RTX" in text:
            base *= 1.8 if text.endswith(("4080", "4090")) else 1.25
        elif getattr(value, "pool", None) and (value.attribute.is_price_key or code == "cpu"):
            step = 0.35 if code == "cpu" else 0.2
            base *= 1 + step * value.pool.index(value.option)
    age = min(5, max(0, timezone.localdate().year - (model.release_year or 2022)))
    base *= DEPRECIATION.get(model.category.slug, 0.9) ** age
    if condition == Condition.USED:
        base *= rng.uniform(0.66, 0.8)
    base *= rng.uniform(0.94, 1.06)
    step = 500 if base < 50000 else 1000
    return max(step, int(round(base / step) * step))


def _description(rng, condition: str) -> str:
    if condition == Condition.NEW:
        parts = [rng.choice(OPENINGS_NEW), rng.choice(CLOSINGS)]
    else:
        parts = [
            rng.choice(OPENINGS_USED),
            rng.choice(USAGE).format(months=rng.choice((4, 6, 8, 10, 12, 14, 18, 24))),
            *rng.sample(DETAILS_USED, 2),
            rng.choice(CLOSINGS),
        ]
    return " ".join(parts)


def _pick(rng, options):
    weights = [max(1, 4 - index) for index in range(len(options))]
    return rng.choices(options, weights)[0]


def _attributes(rng, model: DeviceModel) -> list[AttributeValue]:
    values = []
    allowed = {}
    for item in model.allowed_options.select_related("option__attribute"):
        allowed.setdefault(item.option.attribute, []).append(item.option)
    for attribute, options in allowed.items():
        options.sort(key=lambda option: option.sort_order)
        value = AttributeValue(attribute, option=_pick(rng, options))
        value.pool = options
        values.append(value)
    taken = {value.attribute.pk for value in values}
    specs = {spec.attribute_id for spec in model.specs.all()}
    is_apple = model.brand.name == "Apple"
    for attribute in model.category.attributes.filter(is_variant=True, kind=AttributeKind.CHOICE):
        if attribute.pk in taken or attribute.pk in specs:
            continue
        options = [
            option
            for option in attribute.options.all()
            if is_apple or not option.value.startswith("Apple")
        ]
        if attribute.code in ("ram", "storage"):
            options = options[1:6]
        if options and (attribute.is_required or rng.random() < 0.7):
            value = AttributeValue(attribute, option=_pick(rng, options))
            value.pool = options
            values.append(value)
    for spec in model.specs.select_related("attribute", "option"):
        values.append(
            AttributeValue(spec.attribute, spec.option, spec.value_number, spec.value_bool)
        )
    return values


def _condition_report(rng, category: Category, condition: str) -> dict:
    states = ("perfect", "minor", "minor", "scratches")
    if condition == Condition.NEW:
        return {
            "is_sealed": rng.random() < 0.6,
            "has_receipt": rng.random() < 0.7,
            "package": ["box", "cable", "documents"],
        }
    broken = rng.random() < 0.06
    return {
        "screen_state": rng.choice(states) if category.has_screen else "",
        "body_state": rng.choice(states),
        "battery_health": rng.randint(78, 100) if category.has_battery else None,
        "everything_works": not broken,
        "issues": "Иногда не срабатывает датчик приближения." if broken else "",
        "was_repaired": rng.random() < 0.1,
        "repair_note": "Меняли аккумулятор в сервисе." if rng.random() < 0.1 else "",
        "package": rng.sample(["box", "charger", "cable", "case"], rng.randint(1, 3)),
    }


class DemoBuilder:
    def __init__(self, seed: int = 2026):
        self.rng = random.Random(seed)
        self.now = timezone.now()

    def clear(self) -> int:
        users = User.objects.filter(email__endswith=f"@{DEMO_DOMAIN}")
        count = users.count()
        for photo in AdPhoto.objects.filter(owner__in=users):
            photo.delete()
        users.delete()
        return count

    def users(self, count: int) -> list[User]:
        cities = {c.slug: c for c in City.objects.filter(slug__in=CITY_WEIGHTS)}
        slugs = list(CITY_WEIGHTS)
        weights = [CITY_WEIGHTS[s] for s in slugs]
        users = []
        for index in range(count):
            name = FIRST_NAMES[index % len(FIRST_NAMES)]
            user = User(
                email=f"seller{index + 1:02d}@{DEMO_DOMAIN}",
                first_name=name,
                city=cities[self.rng.choices(slugs, weights)[0]],
                phone=f"+7914{self.rng.randint(1000000, 9999999)}",
                contact_mode=self.rng.choice(list(ContactMode.values)),
                email_verified_at=self.now,
                last_seen_at=self.now - timedelta(minutes=self.rng.randint(1, 60 * 24 * 10)),
                email_on_messages=False,
                email_on_price_drop=False,
                email_on_saved_search=False,
                email_on_moderation=False,
            )
            user.date_joined = self.now - timedelta(days=self.rng.randint(20, 700))
            user.set_password(secrets.token_urlsafe(16))
            users.append(user)
        return User.objects.bulk_create(users)

    @transaction.atomic
    def ads(self, sellers: list[User], count: int) -> list[Ad]:
        photos = _prepare_photos(self.rng)
        self.photo_pool = photos
        models_by_category = {}
        for slug in CATEGORY_WEIGHTS:
            models_by_category[slug] = list(
                DeviceModel.objects.filter(category__slug=slug, is_active=True)
                .select_related("brand", "category")
                .prefetch_related("specs__attribute", "specs__option")
            )
        slugs = [s for s in CATEGORY_WEIGHTS if models_by_category[s]]
        weights = [CATEGORY_WEIGHTS[s] for s in slugs]
        popular = {
            slug: self.rng.sample(
                sorted(models, key=lambda m: -(m.release_year or 0))[:30],
                min(POOL_SIZE.get(slug, 4), len(models)),
            )
            for slug, models in models_by_category.items()
            if models
        }
        created = []
        for _ in range(count):
            slug = self.rng.choices(slugs, weights)[0]
            source = popular[slug] if self.rng.random() < 0.75 else models_by_category[slug]
            model = self.rng.choice(source)
            seller = self.rng.choice(sellers)
            condition = Condition.NEW if self.rng.random() < 0.15 else Condition.USED
            attributes = _attributes(self.rng, model)
            draft = AdDraft(
                fields={
                    "category": model.category,
                    "brand": model.brand,
                    "device_model": model,
                    "custom_model_name": "",
                    "title": "",
                    "description": _description(self.rng, condition),
                    "price": _price(self.rng, model, condition, attributes),
                    "is_negotiable": self.rng.random() < 0.5,
                    "condition": condition,
                    "city": seller.city,
                },
                attributes=attributes,
                condition=_condition_report(self.rng, model.category, condition),
                photos=self._photos(seller, photos.get(slug, [])),
            )
            ad = create_ad(seller, draft)
            self._publish(ad)
            created.append(ad)
        return created

    def _photos(self, owner, pool: list[PreparedPhoto]) -> list[AdPhoto]:
        result = []
        for item in self.rng.sample(pool, min(len(pool), self.rng.randint(1, 3))):
            name = f"{secrets.token_hex(10)}.webp"
            photo = AdPhoto(owner=owner, width=item.width, height=item.height)
            photo.image.save(name, ContentFile(item.image), save=False)
            photo.thumb.save(name, ContentFile(item.thumb), save=False)
            photo.save()
            result.append(photo)
        return result

    def _publish(self, ad: Ad) -> None:
        roll = self.rng.random()
        published = self.now - timedelta(hours=self.rng.randint(1, 24 * 25))
        status = AdStatus.ACTIVE
        if roll < 0.06:
            status = AdStatus.PENDING
            published = None
        elif roll < 0.1:
            status = AdStatus.SOLD
        elif roll < 0.13:
            status = AdStatus.ARCHIVED
        updates = {
            "status": status,
            "published_at": published,
            "bumped_at": published,
            "status_changed_at": published or self.now,
            "views_count": self.rng.randint(5, 400) if published else 0,
            "contacts_shown_count": self.rng.randint(0, 20) if published else 0,
        }
        if status == AdStatus.ACTIVE and self.rng.random() < 0.05:
            updates["pinned_until"] = self.now + timedelta(days=self.rng.randint(1, 3))
        if status == AdStatus.ACTIVE and self.rng.random() < 0.08:
            updates["highlighted_until"] = self.now + timedelta(days=self.rng.randint(1, 7))
        Ad.objects.filter(pk=ad.pk).update(**updates)

    def price_history(self, ads: list[Ad]) -> int:
        changed = 0
        for ad in self.rng.sample(ads, len(ads) // 8):
            ad.refresh_from_db()
            if ad.status != AdStatus.ACTIVE:
                continue
            old = int(ad.price * self.rng.uniform(1.05, 1.15) // 500 * 500)
            PriceChange.objects.create(ad=ad, old_price=old, new_price=ad.price)
            changed += 1
        return changed

    def favorites(self, users: list[User], ads: list[Ad]) -> int:
        active = list(Ad.objects.filter(pk__in=[a.pk for a in ads], status=AdStatus.ACTIVE))
        pairs = set()
        for user in users:
            for ad in self.rng.sample(active, min(len(active), self.rng.randint(0, 6))):
                if ad.seller_id != user.pk:
                    pairs.add((user.pk, ad.pk))
        Favorite.objects.bulk_create(
            [Favorite(user_id=u, ad_id=a) for u, a in pairs], ignore_conflicts=True
        )
        for _, ad_id in pairs:
            Ad.objects.filter(pk=ad_id).update(favorites_count=F("favorites_count") + 1)
        return len(pairs)

    @transaction.atomic
    def problem_ads(self, sellers: list[User]) -> int:
        categories = {c.slug: c for c in Category.objects.filter(slug__in=CATEGORY_WEIGHTS)}
        created = 0
        for slug, model_name, description, price in PROBLEM_ADS:
            model = (
                DeviceModel.objects.filter(category__slug=slug, name__icontains=model_name)
                .select_related("brand", "category")
                .first()
                if model_name
                else None
            )
            seller = self.rng.choice(sellers)
            draft = AdDraft(
                fields={
                    "category": categories[slug],
                    "brand": model.brand if model else None,
                    "device_model": model,
                    "custom_model_name": "" if model else CUSTOM_PROBLEM_TITLE,
                    "title": "" if model else CUSTOM_PROBLEM_TITLE,
                    "description": description,
                    "price": price,
                    "is_negotiable": False,
                    "condition": Condition.USED,
                    "city": seller.city,
                },
                attributes=_attributes(self.rng, model) if model else [],
                condition=_condition_report(self.rng, categories[slug], Condition.USED),
                photos=self._photos(seller, self.photo_pool.get(slug, [])),
            )
            create_ad(seller, draft)
            created += 1
        return created

    def complaints(self, users: list[User], ads: list[Ad]) -> int:
        if len(users) < 4:
            return 0
        active = list(
            Ad.objects.filter(pk__in=[a.pk for a in ads], status=AdStatus.ACTIVE).order_by("pk")
        )
        targets = self.rng.sample(active, min(len(active), 7))
        filed = 0
        for index, ad in enumerate(targets):
            authors = [u for u in users if u.pk != ad.seller_id]
            count = 3 if index == 0 else self.rng.randint(1, 2)
            for author in self.rng.sample(authors, count):
                reason = self.rng.choice(list(COMPLAINT_COMMENTS))
                moderation.file_complaint(
                    author, ad=ad, reason=reason, comment=COMPLAINT_COMMENTS[reason]
                )
                filed += 1
        target, author = self.rng.sample(users, 2)
        moderation.file_complaint(
            author,
            user=target,
            reason=ComplaintReason.FRAUD,
            comment="Взял залог за доставку и перестал отвечать.",
        )
        return filed + 1

    @transaction.atomic
    def deals(self, users: list[User], ads: list[Ad], count: int = 60) -> tuple[int, int]:
        if len(users) < 2:
            return 0, 0
        active = list(
            Ad.objects.filter(pk__in=[ad.pk for ad in ads], status=AdStatus.ACTIVE)
            .select_related("seller")
            .order_by("pk")
        )
        picked = self.rng.sample(active, min(count, len(active)))
        reviews = 0
        for ad in picked:
            buyer = self.rng.choice([user for user in users if user.pk != ad.seller_id])
            asked_at = self.now - timedelta(
                days=self.rng.randint(1, 25), hours=self.rng.randint(0, 12)
            )
            answered_at = asked_at + timedelta(minutes=self.rng.randint(3, 180))
            conversation = Conversation.objects.create(
                ad=ad, buyer=buyer, seller_id=ad.seller_id, last_message_at=answered_at
            )
            question, answer = self.rng.choice(DEAL_DIALOGS)
            for sender, text, sent_at in (
                (buyer, question, asked_at),
                (ad.seller, answer, answered_at),
            ):
                message = Message.objects.create(
                    conversation=conversation, sender=sender, text=text, read_at=sent_at
                )
                Message.objects.filter(pk=message.pk).update(created_at=sent_at)
            if self.rng.random() < 0.7:
                reviews += self._review(buyer, ad.seller, ad, AuthorRole.BUYER, answered_at)
            if self.rng.random() < 0.35:
                reviews += self._review(ad.seller, buyer, ad, AuthorRole.SELLER, answered_at)
        for user in users:
            recalculate_rating(user.pk)
        return len(picked), reviews

    def _review(self, author, target, ad, role, after) -> int:
        if role == AuthorRole.BUYER:
            rating = self.rng.choices(list(RATING_WEIGHTS), list(RATING_WEIGHTS.values()))[0]
            text = self.rng.choice(BUYER_REVIEWS[rating])
        else:
            rating, text = 5, self.rng.choice(SELLER_REVIEWS)
        written_at = after + timedelta(days=self.rng.randint(0, 3), hours=self.rng.randint(1, 8))
        review = Review.objects.create(
            author=author, target=target, ad=ad, author_role=role, rating=rating, text=text
        )
        updates = {"created_at": written_at}
        if role == AuthorRole.BUYER and self.rng.random() < 0.3:
            updates.update(reply_text=self.rng.choice(REPLIES), reply_at=written_at)
        Review.objects.filter(pk=review.pk).update(**updates)
        return 1

    def finish(self, ads: list[Ad]) -> int:
        for ad in ads:
            index_ad(ad)
        return recalculate_price_stats()
