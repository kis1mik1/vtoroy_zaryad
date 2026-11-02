import re
from dataclasses import asdict, dataclass
from datetime import timedelta

from django.contrib.postgres.search import TrigramSimilarity
from django.db.models import Q
from django.utils import timezone

from apps.ads.models import Ad, AdStatus, PriceStat
from apps.ads.selectors import MARKET_MIN_SAMPLE
from apps.core.text import format_price

from .models import RejectionReason
from .text import ad_text

REJECT = "reject"
REVIEW = "review"

DUPLICATE_WINDOW = timedelta(days=30)
DUPLICATE_TITLE_SIMILARITY = 0.7
DUPLICATE_TEXT_SIMILARITY = 0.6
SYMBOLIC_PRICE = 10
FRAUD_PRICE_RATIO = 0.5


@dataclass(frozen=True)
class Flag:
    code: str
    text: str
    severity: str
    reason: str
    fragment: str = ""
    related_ad: int | None = None

    def as_dict(self) -> dict:
        return {key: value for key, value in asdict(self).items() if value not in ("", None)}


@dataclass(frozen=True)
class Rule:
    code: str
    text: str
    severity: str
    reason: str
    pattern: re.Pattern


def rule(code, text, severity, reason, pattern) -> Rule:
    return Rule(code, text, severity, reason, re.compile(pattern))


TEXT_RULES = (
    rule(
        "phone",
        "Номер телефона в тексте",
        REJECT,
        RejectionReason.CONTACTS,
        r"(?<![\d+])(?:(?:\+7|8)[\s\-(]*\d{3}|9\d{2})[\s\-)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}(?!\d)",
    ),
    rule(
        "email",
        "Адрес почты в тексте",
        REJECT,
        RejectionReason.CONTACTS,
        r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}",
    ),
    rule(
        "link",
        "Ссылка в тексте",
        REJECT,
        RejectionReason.CONTACTS,
        r"(?:https?://|www\.)\S+|\bt\.me/\S+"
        r"|\b[a-z0-9-]{2,}\.(?:ru|com|net|org|su|me|io|info|biz|shop|store|online|site|pro"
        r"|cc|ly|link|to|gg|app)\b(?:/\S*)?|\b[а-я0-9-]{2,}\.рф\b",
    ),
    rule(
        "handle",
        "Имя пользователя в мессенджере",
        REJECT,
        RejectionReason.CONTACTS,
        r"(?<![\w.])@[a-z0-9_]{4,}",
    ),
    rule(
        "messenger",
        "Упоминание мессенджера",
        REVIEW,
        RejectionReason.CONTACTS,
        r"\b(?:telegram|телеграм+\w*|телег[аеиу]|тг|tg|whats\s?app|вотс?ап\w*|ватс?ап\w*"
        r"|вацап\w*|ватцап\w*|viber|вайбер\w*|vk|вк|вконтакте|instagram|инстаграм\w*|инст[аеу])\b",
    ),
    rule(
        "weapons",
        "Оружие или боеприпасы",
        REJECT,
        RejectionReason.FORBIDDEN,
        r"\b(?:огнестрел\w*|травмат(?:ическ\w*)?\b|ружь[еяю]\w*|обрез(?:ы|ов)?\b"
        r"|патрон(?:ы|ов)\b|боеприпас\w*|взрывчатк\w*|тротил\w*|кастет\w*"
        r"|пневматическ\w* (?:пистолет|винтовк)\w*|нож[- ]бабочк\w*)",
    ),
    rule(
        "drugs",
        "Наркотики или лекарства",
        REJECT,
        RejectionReason.FORBIDDEN,
        r"\b(?:наркотик\w*|мефедрон\w*|амфетамин\w*|гашиш\w*|марихуан\w*|каннабис\w*"
        r"|кокаин\w*|героин\w*|экстази|спайс\w*|псилоциб\w*|лекарств\w*|рецептурн\w*"
        r"|антибиотик\w*|трамадол\w*|прегабалин\w*)",
    ),
    rule(
        "spy",
        "Средства негласного получения информации",
        REJECT,
        RejectionReason.FORBIDDEN,
        r"\b(?:скрыт\w* (?:видео)?(?:камер|микрофон)\w*|шпион\w*|жуч(?:ок|ки|ка)\b"
        r"|прослушк\w*|подслушивающ\w*|глушилк\w*"
        r"|подавител\w* (?:связи|сигнал\w*|gsm|gps|wi-?fi|сотов\w*))",
    ),
    rule(
        "locked",
        "Краденое или заблокированное устройство",
        REJECT,
        RejectionReason.FORBIDDEN,
        r"(?<!не )\b(?:краден\w*|ворован\w*)|\bнайден\w* на улице"
        r"|\bнашел (?:телефон|айфон|смартфон)|\bicloud lock|(?<!не )\bзалочен\w*"
        r"|(?<!не )\bзаблокирован\w* (?:по |на )?(?:imei|имей)|\bпривязан\w* к чужо\w+",
    ),
    rule(
        "services",
        "Похоже на услугу",
        REVIEW,
        RejectionReason.SERVICES,
        r"\b(?:услуг\w*|ремонт\w* (?:телефонов|смартфонов|ноутбуков|компьютеров|техники|айфонов"
        r"|iphone|любой|любых)|выезд мастера|выезжаю|прошивк\w* (?:на заказ|под ключ)"
        r"|(?:настрою|установлю|прошью|почищу|отремонтирую|починю)\b|обмен валют\w*"
        r"|соберу (?:пк|компьютер))",
    ),
    rule(
        "realty",
        "Похоже на недвижимость",
        REVIEW,
        RejectionReason.NOT_ELECTRONICS,
        r"\b(?:квартир\w*|комнат[ау] в|аренд\w*|сдам|сниму|дач[аиу]\b|земельн\w* участ\w*"
        r"|недвижимост\w*|ипотек\w*)",
    ),
    rule(
        "auto",
        "Похоже на автомобиль или запчасти",
        REVIEW,
        RejectionReason.NOT_ELECTRONICS,
        r"\b(?:автомобил\w*|пробег\w*|кузов\w*|двигател\w*|коробк\w* передач|шин[ыа]\b"
        r"|резин[ау] (?:зимн|летн)\w*|диски r\d{2}|птс\b|растаможен\w*)",
    ),
    rule(
        "animals",
        "Похоже на животных",
        REVIEW,
        RejectionReason.NOT_ELECTRONICS,
        r"\b(?:щен(?:ок|ки|ят\w*)|котен(?:ок|ка)|котят\w*|кошк[аиу]\b|собак[аиу]\b|попуга\w*"
        r"|хомяк\w*|породист\w*|прививк\w*)",
    ),
    rule(
        "clothes",
        "Похоже на одежду или обувь",
        REVIEW,
        RejectionReason.NOT_ELECTRONICS,
        r"\b(?:куртк\w*|пальто|плать[еяю]\w*|джинс\w*|кроссовк\w*|ботинк\w*|сапог\w*|шуб[аыу]\b"
        r"|футболк\w*|толстовк\w*|худи\b)",
    ),
    rule(
        "bulk",
        "Похоже на несколько товаров или продажу оптом",
        REVIEW,
        RejectionReason.MULTIPLE,
        r"\b(?:оптом|опт\b|оптов\w*|в ассортименте|любые модели|много моделей|все модели"
        r"|под заказ|в наличии (?:много|разные|любые)|продам вс[её] (?:сразу|за раз|разом)"
        r"|лот(?:ом)? из|партия\b)",
    ),
    rule(
        "prepayment",
        "Просьба о предоплате",
        REVIEW,
        RejectionReason.FRAUD,
        r"(?<!без )\bпредоплат\w*\b(?! не\b)|\b(?:переведите|перевод|оплата) на карту"
        r"|\bотправлю после оплаты|\bсначала оплата",
    ),
    rule(
        "card",
        "Номер банковской карты",
        REVIEW,
        RejectionReason.FRAUD,
        r"(?<!\d)(?:\d{4}[\s-]?){3}\d{4}(?!\d)",
    ),
)


def text_flags(text: str) -> list[Flag]:
    flags = []
    for item in TEXT_RULES:
        match = item.pattern.search(text)
        if match:
            flags.append(
                Flag(item.code, item.text, item.severity, item.reason, match.group(0).strip())
            )
    return flags


def duplicate_flag(ad: Ad) -> Flag | None:
    candidates = (
        Ad.objects.alive()
        .filter(
            seller_id=ad.seller_id,
            category_id=ad.category_id,
            status__in=(AdStatus.ACTIVE, AdStatus.PENDING),
            created_at__gte=timezone.now() - DUPLICATE_WINDOW,
        )
        .exclude(pk=ad.pk)
        .annotate(
            title_similarity=TrigramSimilarity("title", ad.title),
            text_similarity=TrigramSimilarity("description", ad.description),
        )
    )
    same_item = Q(title_similarity__gte=DUPLICATE_TITLE_SIMILARITY)
    if ad.device_model_id:
        same_item |= Q(device_model_id=ad.device_model_id)
    duplicate = (
        candidates.filter(same_item, text_similarity__gte=DUPLICATE_TEXT_SIMILARITY)
        .order_by("-text_similarity")
        .first()
    )
    if duplicate is None:
        return None
    return Flag(
        "duplicate",
        f"У продавца уже есть похожее объявление: «{duplicate.title}»",
        REVIEW,
        RejectionReason.DUPLICATE,
        related_ad=duplicate.pk,
    )


def price_flags(ad: Ad) -> list[Flag]:
    if ad.price <= SYMBOLIC_PRICE:
        return [
            Flag(
                "symbolic_price",
                f"Символическая цена: {format_price(ad.price)}",
                REJECT,
                RejectionReason.PRICE,
            )
        ]
    if not ad.device_model_id:
        return []
    stat = PriceStat.objects.filter(
        device_model_id=ad.device_model_id,
        condition=ad.condition,
        price_key=ad.price_key,
        sample_size__gte=MARKET_MIN_SAMPLE,
    ).first()
    if stat is None or ad.price >= stat.median * FRAUD_PRICE_RATIO:
        return []
    ratio = f"{stat.median / ad.price:.1f}".replace(".", ",")
    return [
        Flag(
            "low_price",
            f"Цена в {ratio} раза ниже рынка: обычно {format_price(stat.median)}",
            REVIEW,
            RejectionReason.FRAUD,
        )
    ]


def check_rules(ad: Ad) -> list[Flag]:
    flags = text_flags(ad_text(ad.title, ad.description))
    duplicate = duplicate_flag(ad)
    if duplicate:
        flags.append(duplicate)
    flags.extend(price_flags(ad))
    return flags
