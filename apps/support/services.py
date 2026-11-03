from django.conf import settings
from django.db import transaction
from django.urls import reverse

from apps.core.email import send_templated_email
from apps.notifications.models import NotificationKind
from apps.notifications.services import notify

from .models import SupportTicket, TicketReply, TicketStatus


@transaction.atomic
def create_ticket(*, user, name: str, email: str, topic: str, subject: str, message: str):
    ticket = SupportTicket.objects.create(
        user=user if user and user.is_authenticated else None,
        name=name.strip(),
        email=email,
        topic=topic,
        subject=subject.strip(),
        message=message.strip(),
    )
    admin_url = reverse("admin:support_supportticket_change", args=[ticket.pk])
    send_templated_email(
        settings.SUPPORT_EMAIL,
        "support_ticket",
        {"ticket": ticket, "admin_ticket_url": f"{settings.SITE_URL}{admin_url}"},
        reply_to=[email],
    )
    send_templated_email(email, "support_received", {"ticket": ticket})
    return ticket


@transaction.atomic
def reply(ticket: SupportTicket, author, message: str) -> TicketReply:
    answer = TicketReply.objects.create(ticket=ticket, author=author, message=message.strip())
    if ticket.status == TicketStatus.NEW:
        ticket.status = TicketStatus.ANSWERED
        ticket.save(update_fields=["status", "updated_at"])
    send_templated_email(ticket.email, "support_reply", {"ticket": ticket, "reply": answer})
    if ticket.user_id and ticket.user.is_active:
        notify(
            ticket.user,
            NotificationKind.ACCOUNT,
            f"Ответ поддержки на обращение № {ticket.pk}",
            answer.message[:300],
            url=reverse("support:tickets"),
            email=False,
        )
    return answer
