from datetime import timedelta

import pytest
from django.conf import settings
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.factories import UserFactory
from apps.core import captcha
from apps.notifications.models import Notification
from apps.support import services
from apps.support.models import FAQItem, SupportTicket, TicketReply, TicketStatus, TicketTopic

pytestmark = pytest.mark.django_db

CONTACT = {
    "name": "Ирина",
    "email": "irina@example.com",
    "topic": TicketTopic.PAYMENT,
    "subject": "Не применилось закрепление",
    "message": "Оплатила закрепление вчера, платёж № 12, но объявление не наверху.",
}
PASSED = {captcha.TOKEN_FIELD: captcha.TEST_TOKEN}


def test_faq_shows_sections_from_migration(client):
    page = client.get(reverse("support:faq")).content.decode()

    for title in ("Объявления", "Покупка и безопасность", "Продвижение и оплата", "Аккаунт"):
        assert title in page
    assert "Сколько стоит размещение?" in page


def test_faq_search_understands_word_forms(client):
    response = client.get(reverse("support:faq"), {"q": "оплатил продвижение"})

    results = response.context["results"]
    assert results
    assert "оплат" in results[0].question.lower()


def test_faq_search_returns_fragment_for_htmx(client):
    response = client.get(
        reverse("support:faq"),
        {"q": "заблокировали"},
        HTTP_HX_REQUEST="true",
        HTTP_HX_TARGET="faq-results",
    )

    page = response.content.decode()
    assert "<html" not in page
    assert "Почему меня заблокировали?" in page


def test_faq_search_without_results_offers_contact(client):
    page = client.get(reverse("support:faq"), {"q": "квадрокоптер подводный"}).content.decode()

    assert "Ничего не нашлось" in page
    assert reverse("support:contact") in page


def test_unpublished_answers_are_hidden(client):
    FAQItem.objects.filter(question="Сколько стоит размещение?").update(is_published=False)

    assert "Сколько стоит размещение?" not in client.get(reverse("support:faq")).content.decode()


def test_contact_requires_captcha(client):
    response = client.post(reverse("support:contact"), CONTACT)

    assert response.status_code == 400
    assert "Подтвердите, что вы не робот." in response.content.decode()
    assert not SupportTicket.objects.exists()


def test_contact_creates_ticket_and_emails(client, run_on_commit):
    with run_on_commit():
        response = client.post(reverse("support:contact"), {**CONTACT, **PASSED})

    ticket = SupportTicket.objects.get()
    assert response.url == reverse("support:contact_sent")
    assert (ticket.email, ticket.topic, ticket.user) == ("irina@example.com", "payment", None)
    to_support, to_user = sorted(
        mail.outbox, key=lambda message: message.to != [settings.SUPPORT_EMAIL]
    )
    assert to_support.to == [settings.SUPPORT_EMAIL]
    assert to_support.reply_to == ["irina@example.com"]
    assert f"№ {ticket.pk}" in to_support.subject
    assert to_user.to == ["irina@example.com"]
    assert f"Обращение № {ticket.pk} принято" in to_user.subject
    assert f"Обращение № {ticket.pk} принято" in client.get(response.url).content.decode()


def test_signed_in_user_writes_from_account(auth_client, user):
    page = auth_client.get(reverse("support:contact")).content.decode()
    assert 'name="email"' not in page

    data = {key: value for key, value in CONTACT.items() if key not in ("name", "email")}
    auth_client.post(reverse("support:contact"), {**data, **PASSED})

    ticket = SupportTicket.objects.get()
    assert (ticket.user, ticket.email, ticket.name) == (user, user.email, user.first_name)


def test_topic_can_be_preselected(client):
    response = client.get(reverse("support:contact"), {"topic": "account"})

    assert response.context["form"]["topic"].value() == "account"


def test_contact_is_rate_limited(client):
    url = reverse("support:contact")
    for _ in range(5):
        client.post(url, {**CONTACT, **PASSED})

    assert client.post(url, {**CONTACT, **PASSED}).status_code == 429
    assert SupportTicket.objects.count() == 5


def test_banned_user_can_reach_support(client):
    user = UserFactory(banned_until=timezone.now() + timedelta(days=3), ban_reason="Спам")
    client.force_login(user)

    assert client.get(reverse("ads:home")).status_code == 403
    assert client.get(reverse("support:contact")).status_code == 200


def test_reply_from_admin_emails_user(client, run_on_commit):
    author = UserFactory()
    ticket = services.create_ticket(user=author, **{**CONTACT, "email": author.email})
    mail.outbox.clear()
    admin = UserFactory(is_staff=True, is_superuser=True)
    client.force_login(admin)
    url = reverse("admin:support_supportticket_change", args=[ticket.pk])
    formsets = client.get(url).context["inline_admin_formsets"]
    data = {"status": TicketStatus.NEW}
    for inline in formsets:
        management = inline.formset.management_form
        data.update(
            {management.add_prefix(name): management[name].value() for name in management.fields}
        )
        if inline.formset.extra:
            data[inline.formset.forms[0].add_prefix("message")] = "Закрепление применили вручную."

    with run_on_commit():
        response = client.post(url, data)

    assert response.status_code == 302
    reply = TicketReply.objects.get()
    ticket.refresh_from_db()
    assert (reply.author, reply.message) == (admin, "Закрепление применили вручную.")
    assert ticket.status == TicketStatus.ANSWERED
    assert [message.to for message in mail.outbox] == [[author.email]]
    assert "Закрепление применили вручную." in mail.outbox[0].body
    assert Notification.objects.filter(user=author, title__contains=f"№ {ticket.pk}").exists()


def test_my_tickets_show_replies(client):
    author = UserFactory()
    ticket = services.create_ticket(user=author, **{**CONTACT, "email": author.email})
    services.reply(ticket, None, "Проверили, всё работает.")
    client.force_login(author)

    page = client.get(reverse("support:tickets")).content.decode()
    assert "Не применилось закрепление" in page
    assert "Проверили, всё работает." in page

    client.force_login(UserFactory())
    assert (
        "Не применилось закрепление" not in client.get(reverse("support:tickets")).content.decode()
    )
