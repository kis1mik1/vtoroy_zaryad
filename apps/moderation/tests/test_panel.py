import pytest
from django.core import mail
from django.urls import reverse

from apps.accounts.models import BanRecord
from apps.accounts.tests.factories import UserFactory
from apps.ads.models import AdStatus
from apps.ads.tests.helpers import publish
from apps.moderation import services
from apps.moderation.models import (
    ActionKind,
    Complaint,
    ComplaintReason,
    ComplaintStatus,
    ModerationAction,
)
from apps.notifications.models import Notification

from .helpers import submit

pytestmark = pytest.mark.django_db


@pytest.fixture
def queued(phones, models, run_on_commit):
    models.photos = [0.15]
    models.photo_label = "кошка"
    with run_on_commit():
        ad = submit(phones, description="Звоните в вотсап, телефон в отличном состоянии.")
    ad.refresh_from_db()
    assert ad.review_queued_at is not None
    return ad


@pytest.mark.parametrize(
    "name",
    ["moderation:queue", "moderation:rejected", "moderation:history", "moderation:complaints"],
)
def test_panel_closed_to_regular_users(client, name):
    assert client.get(reverse(name)).status_code == 302
    client.force_login(UserFactory())
    assert client.get(reverse(name)).status_code == 403


def test_queue_shows_reasons(moderator_client, queued):
    page = moderator_client.get(reverse("moderation:queue")).content.decode()

    assert queued.title in page
    assert "Упоминание мессенджера" in page
    assert "Фото 1 не похоже на технику" in page


def test_menu_has_moderation_link_with_counter(moderator_client, queued):
    page = moderator_client.get(reverse("ads:home")).content.decode()

    assert reverse("moderation:queue") in page


def test_review_page_highlights_found_fragments(moderator_client, queued):
    page = moderator_client.get(reverse("moderation:ad", args=[queued.pk])).content.decode()

    assert "<mark>вотсап</mark>" in page
    assert "mod-photo--flagged" in page
    assert "кошка · техника 15%" in page


def test_approve_from_review_page(moderator_client, moderator, queued):
    response = moderator_client.post(
        reverse("moderation:ad_decide", args=[queued.pk]), {"decision": "approve"}
    )

    queued.refresh_from_db()
    assert response.status_code == 302
    assert queued.status == AdStatus.ACTIVE
    assert queued.review_queued_at is None
    action = ModerationAction.objects.get(ad=queued)
    assert (action.action, action.moderator) == (ActionKind.APPROVE, moderator)


def test_reject_needs_explanation_for_other_reason(moderator_client, queued):
    url = reverse("moderation:ad_decide", args=[queued.pk])

    response = moderator_client.post(url, {"decision": "reject", "reason": "other"})
    assert response.status_code == 400
    assert "Опишите причину" in response.content.decode()

    moderator_client.post(
        url, {"decision": "reject", "reason": "contacts", "comment": "Уберите мессенджер"}
    )
    queued.refresh_from_db()
    assert queued.status == AdStatus.REJECTED
    assert queued.rejection_reason == "В описании есть контакты или ссылки. Уберите мессенджер"


def test_taking_down_active_ad(moderator_client, phones):
    ad = publish(phones)

    moderator_client.post(
        reverse("moderation:ad_decide", args=[ad.pk]), {"decision": "reject", "reason": "fraud"}
    )

    ad.refresh_from_db()
    assert ad.status == AdStatus.REJECTED
    assert ModerationAction.objects.get(ad=ad).action == ActionKind.TAKE_DOWN


def test_decision_moves_to_next_in_queue(moderator_client, phones, models, run_on_commit):
    models.images_error = "нет весов"
    with run_on_commit():
        first, second = submit(phones), submit(phones)

    response = moderator_client.post(
        reverse("moderation:ad_decide", args=[first.pk]), {"decision": "approve"}
    )

    assert response.url == reverse("moderation:ad", args=[second.pk])


def test_auto_rejected_can_be_restored(moderator_client, phones, models, run_on_commit):
    with run_on_commit():
        ad = submit(phones, description="Подробности на avito.ru, там больше фото.")
    ad.refresh_from_db()
    assert ad.status == AdStatus.REJECTED

    page = moderator_client.get(reverse("moderation:rejected")).content.decode()
    assert ad.title in page

    moderator_client.post(
        reverse("moderation:ad_decide", args=[ad.pk]), {"decision": "approve", "next": "rejected"}
    )
    ad.refresh_from_db()
    assert ad.status == AdStatus.ACTIVE
    assert ModerationAction.objects.get(ad=ad).action == ActionKind.RESTORE
    assert ad.title not in moderator_client.get(reverse("moderation:rejected")).content.decode()


def test_complaints_page_and_dismiss(moderator_client, phones):
    ad = publish(phones)
    services.file_complaint(UserFactory(), ad=ad, reason=ComplaintReason.SOLD, comment="Продано")
    url = reverse("moderation:complaints")

    assert "Продано" in moderator_client.get(url).content.decode()

    moderator_client.post(reverse("moderation:complaints_dismiss", args=["ad", ad.pk]))
    assert Complaint.objects.get().status == ComplaintStatus.DISMISSED
    assert "Продано" in moderator_client.get(url, {"status": "dismissed"}).content.decode()


def test_ban_user_from_card(moderator_client, moderator, run_on_commit):
    target = UserFactory(first_name="Фёдор")
    services.file_complaint(UserFactory(), user=target, reason=ComplaintReason.FRAUD)

    card = moderator_client.get(reverse("moderation:user", args=[target.pk])).content.decode()
    assert "Заблокировать" in card

    with run_on_commit():
        moderator_client.post(
            reverse("moderation:user_ban", args=[target.pk]),
            {"reason": "Мошенничество", "term": "7", "comment": "Брал предоплату"},
        )

    target.refresh_from_db()
    assert target.is_banned
    assert target.ban_reason == "Мошенничество. Брал предоплату"
    assert BanRecord.objects.get(user=target).moderator == moderator
    assert Complaint.objects.get(target_user=target).status == ComplaintStatus.ACCEPTED
    assert any("Аккаунт заблокирован" in message.subject for message in mail.outbox)


def test_banned_seller_ads_disappear_and_return(moderator_client, phones):
    ad = publish(phones)
    detail = reverse("ads:detail", args=[ad.pk, ad.slug])

    moderator_client.post(
        reverse("moderation:user_ban", args=[ad.seller.pk]),
        {"reason": "Спам и повторяющиеся объявления", "term": "forever"},
    )
    moderator_client.logout()
    assert moderator_client.get(detail).status_code == 404

    moderator_client.force_login(UserFactory(is_staff=True, is_superuser=True))
    moderator_client.post(reverse("moderation:user_unban", args=[ad.seller.pk]))
    moderator_client.logout()
    assert moderator_client.get(detail).status_code == 200
    assert Notification.objects.filter(user=ad.seller, title="Блокировка снята").exists()


def test_staff_cannot_be_banned_from_panel(moderator_client):
    colleague = UserFactory(is_staff=True)

    moderator_client.post(
        reverse("moderation:user_ban", args=[colleague.pk]),
        {"reason": "Мошенничество", "term": "1"},
    )

    colleague.refresh_from_db()
    assert not colleague.is_banned


def test_history_lists_decisions(moderator_client, moderator, phones):
    ad = publish(phones)
    services.reject(ad, moderator, "photos", "Нужны свои фото")

    page = moderator_client.get(reverse("moderation:history")).content.decode()

    assert ad.title in page
    assert "Снято с публикации" in page
    assert "Нужны свои фото" in page


def test_admin_shows_checks_on_ad(admin_client, queued):
    page = admin_client.get(reverse("admin:ads_ad_change", args=[queued.pk])).content.decode()

    assert "Передано модератору" in page
