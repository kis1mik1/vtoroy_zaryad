from django.conf import settings
from django.db import transaction
from django.template.loader import render_to_string

from .tasks import send_email


def render_email(template: str, context: dict) -> tuple[str, str, str]:
    context = {
        "site_name": settings.SITE_NAME,
        "site_url": settings.SITE_URL,
        "support_email": settings.SUPPORT_EMAIL,
        **context,
    }
    subject = " ".join(render_to_string(f"emails/{template}/subject.txt", context).split())
    text = render_to_string(f"emails/{template}/body.txt", context).strip() + "\n"
    html = render_to_string(f"emails/{template}/body.html", context)
    return subject, text, html


def send_templated_email(recipients, template: str, context: dict, *, reply_to=None) -> None:
    if isinstance(recipients, str):
        recipients = [recipients]
    subject, text, html = render_email(template, context)
    transaction.on_commit(lambda: send_email.delay(subject, list(recipients), text, html, reply_to))
