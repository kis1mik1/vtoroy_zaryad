import pytest
from django.urls import reverse

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
    RejectionReason,
)
from apps.notifications.models import Notification

pytestmark = pytest.mark.django_db


def complain(ad, author=None, reason=ComplaintReason.FRAUD):
    return services.file_complaint(author or UserFactory(), ad=ad, reason=reason)


def test_complaint_is_saved(phones):
    ad = publish(phones)
    author = UserFactory()

    complaint = services.file_complaint(
        author, ad=ad, reason=ComplaintReason.WRONG_PRICE, comment="  Просит больше  "
    )

    assert complaint.status == ComplaintStatus.NEW
    assert complaint.comment == "Просит больше"
    assert complaint.target == ad


@pytest.mark.parametrize(
    ("setup", "message"),
    [
        ("own", "На своё объявление пожаловаться нельзя."),
        ("twice", "Вы уже пожаловались на это объявление."),
        ("sold", "Объявление уже снято с публикации."),
    ],
)
def test_complaint_rules(phones, setup, message):
    ad = publish(phones)
    author = ad.seller if setup == "own" else UserFactory()
    if setup == "twice":
        complain(ad, author)
    if setup == "sold":
        ad.status = AdStatus.SOLD
        ad.save()

    with pytest.raises(services.ModerationError, match=message):
        complain(ad, author)


def test_three_complaints_hide_ad_until_review(phones):
    ad = publish(phones)

    complain(ad)
    complain(ad)
    ad.refresh_from_db()
    assert ad.status == AdStatus.ACTIVE

    complain(ad)
    ad.refresh_from_db()
    assert ad.status == AdStatus.PENDING
    assert ad.review_queued_at is not None
    action = ModerationAction.objects.get(ad=ad)
    assert action.action == ActionKind.REVIEW
    assert action.moderator is None
    assert Notification.objects.filter(
        user=ad.seller, title__startswith="Объявление снова на проверке"
    ).exists()


def test_dismissed_complaints_do_not_count_again(phones, moderator):
    ad = publish(phones)
    complain(ad)
    complain(ad)
    services.dismiss_complaints(moderator, ad=ad)

    complain(ad)

    ad.refresh_from_db()
    assert ad.status == AdStatus.ACTIVE


def test_rejecting_ad_accepts_complaints_and_thanks_authors(phones, moderator):
    ad = publish(phones)
    complaint = complain(ad)

    services.reject(ad, moderator, RejectionReason.FRAUD)

    complaint.refresh_from_db()
    assert complaint.status == ComplaintStatus.ACCEPTED
    assert complaint.handled_by == moderator
    assert Notification.objects.filter(user=complaint.author, title="Жалоба рассмотрена").exists()


def test_approving_after_complaints_dismisses_them(phones, moderator):
    ad = publish(phones)
    complaints = [complain(ad) for _ in range(3)]

    services.approve(ad, moderator)

    ad.refresh_from_db()
    assert ad.status == AdStatus.ACTIVE
    assert {c.status for c in Complaint.objects.filter(pk__in=[c.pk for c in complaints])} == {
        ComplaintStatus.DISMISSED
    }


def test_user_complaint_and_repeat_while_open(db):
    author, target = UserFactory(), UserFactory()
    services.file_complaint(author, user=target, reason=ComplaintReason.INSULT)

    with pytest.raises(services.ModerationError):
        services.file_complaint(author, user=target, reason=ComplaintReason.SPAM)
    with pytest.raises(services.ModerationError):
        services.file_complaint(target, user=target, reason=ComplaintReason.SPAM)


def test_complaint_modal_flow(client, phones):
    ad = publish(phones)
    client.force_login(UserFactory())
    url = reverse("moderation:complain_ad", args=[ad.pk])

    form = client.get(url, headers={"HX-Request": "true"})
    assert "Пожаловаться на объявление" in form.content.decode()
    assert "Уже продано" in form.content.decode()

    sent = client.post(
        url, {"reason": "other", "comment": "Фото из интернета"}, headers={"HX-Request": "true"}
    )

    assert "Жалоба отправлена" in sent.content.decode()
    assert Complaint.objects.get(ad=ad).comment == "Фото из интернета"


def test_other_reason_needs_comment(client, phones):
    ad = publish(phones)
    client.force_login(UserFactory())

    response = client.post(reverse("moderation:complain_ad", args=[ad.pk]), {"reason": "other"})

    assert response.status_code == 400
    assert "Расскажите, что случилось." in response.content.decode()
    assert not Complaint.objects.exists()


def test_repeat_complaint_shows_explanation(client, phones):
    ad = publish(phones)
    author = UserFactory()
    complain(ad, author)
    client.force_login(author)

    response = client.post(reverse("moderation:complain_ad", args=[ad.pk]), {"reason": "fraud"})

    assert response.status_code == 400
    assert "Вы уже пожаловались" in response.content.decode()


def test_unverified_user_cannot_complain(client, phones):
    ad = publish(phones)
    client.force_login(UserFactory(unverified=True))

    response = client.post(reverse("moderation:complain_ad", args=[ad.pk]), {"reason": "fraud"})

    assert response.status_code == 403
    assert not Complaint.objects.exists()


def test_complaint_links_shown_to_others_only(client, phones):
    ad = publish(phones)
    detail = reverse("ads:detail", args=[ad.pk, ad.slug])

    assert "Пожаловаться на объявление" in client.get(detail).content.decode()
    client.force_login(ad.seller)
    assert "Пожаловаться на объявление" not in client.get(detail).content.decode()


def test_user_complaint_from_profile(client, phones):
    ad = publish(phones)
    client.force_login(UserFactory())

    page = client.get(reverse("ads:profile", args=[ad.seller.pk])).content.decode()
    assert "Пожаловаться на пользователя" in page

    client.post(
        reverse("moderation:complain_user", args=[ad.seller.pk]),
        {"reason": "insult", "comment": ""},
    )
    assert Complaint.objects.get(target_user=ad.seller).reason == ComplaintReason.INSULT
