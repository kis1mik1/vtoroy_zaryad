from smtplib import SMTPException

from celery import shared_task
from django.core.mail import EmailMultiAlternatives


@shared_task(
    autoretry_for=(SMTPException, OSError),
    retry_backoff=30,
    retry_backoff_max=60 * 30,
    max_retries=6,
)
def send_email(subject: str, recipients: list[str], text: str, html: str, reply_to=None):
    message = EmailMultiAlternatives(subject, text, to=recipients, reply_to=reply_to)
    message.attach_alternative(html, "text/html")
    message.send()
