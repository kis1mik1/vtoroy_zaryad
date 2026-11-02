import re

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

from ..ml.text import OTHER
from ..models import Verdict

register = template.Library()

VERDICT_TONES = {
    Verdict.APPROVED: "success",
    Verdict.MANUAL: "warning",
    Verdict.REJECTED: "danger",
}


@register.filter
def percent(value) -> str:
    if value is None:
        return "—"
    return f"{round(float(value) * 100)}%"


@register.filter
def verdict_tone(value: str) -> str:
    return VERDICT_TONES.get(value, "")


@register.filter
def current_check(ad):
    checks = getattr(ad, "check_list", None) or []
    if checks and checks[0].created_at >= ad.status_changed_at:
        return checks[0]
    return None


@register.filter
def text_label(check) -> str:
    if not check.text_label:
        return "не проверен"
    if check.text_label == OTHER:
        return "не электроника"
    return check.predicted_category.name if check.predicted_category else check.text_label


@register.simple_tag
def photo_score(check, photo):
    if check is None:
        return None
    return next((item for item in check.image_scores if item["photo"] == photo.pk), None)


@register.filter
def highlight(text: str, check) -> str:
    html = escape(text)
    flags = getattr(check, "rule_flags", None) or []
    fragments = {flag["fragment"] for flag in flags if flag.get("fragment")}
    for fragment in sorted(fragments, key=len, reverse=True):
        pattern = re.compile(re.escape(escape(fragment)), re.IGNORECASE)
        html = pattern.sub(lambda match: f"<mark>{match.group(0)}</mark>", html)
    return mark_safe(html.replace("\n", "<br>"))
