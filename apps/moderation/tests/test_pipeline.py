import pytest
from django.test import override_settings

from apps.ads import services as ads_services
from apps.ads.models import AdPhoto, AdStatus
from apps.ads.tests.helpers import publish
from apps.moderation import pipeline
from apps.moderation.ml.text import OTHER
from apps.moderation.models import ModerationCheck, RejectionReason, Verdict
from apps.moderation.services import run_auto_check
from apps.notifications.models import Notification

from .helpers import submit

pytestmark = pytest.mark.django_db

NAMES = {"phones-test": "Телефоны", "audio": "Аудио"}


def decide(ad):
    return pipeline.decide(ad, pipeline.inspect(ad), NAMES)


def test_confident_electronics_is_approved(phones, models):
    decision = decide(submit(phones))

    assert decision.verdict == Verdict.APPROVED
    assert decision.reasons == []


def test_contacts_are_rejected_with_fragment(phones, models):
    ad = submit(phones, description="Всё работает. Звоните +7 914 123-45-67, отвечу сразу.")

    decision = decide(ad)

    assert decision.verdict == Verdict.REJECTED
    assert decision.reason_code == RejectionReason.CONTACTS
    assert "+7 914 123-45-67" in decision.message


def test_forbidden_goods_are_rejected_with_rule_name(phones, models):
    ad = submit(phones, description="Телефон заблокирован по IMEI, продаю на запчасти целиком.")

    decision = decide(ad)

    assert decision.reason_code == RejectionReason.FORBIDDEN
    assert "заблокированное устройство" in decision.message


def test_text_and_photos_both_against_electronics_reject(phones, models):
    models.text = {"phones-test": 0.03, OTHER: 0.97}
    models.photos = [0.1]
    models.photo_label = "обувь"

    decision = decide(submit(phones))

    assert decision.verdict == Verdict.REJECTED
    assert decision.reason_code == RejectionReason.NOT_ELECTRONICS


def test_text_alone_is_not_enough_to_reject(phones, models):
    models.text = {"phones-test": 0.03, OTHER: 0.97}

    decision = decide(submit(phones))

    assert decision.verdict == Verdict.MANUAL
    assert any("не похоже на электронику" in reason for reason in decision.reasons)


def test_unavailable_photo_check_sends_to_moderator(phones, models):
    models.images_error = "Не скачаны веса CLIP"

    decision = decide(submit(phones))

    assert decision.verdict == Verdict.MANUAL
    assert decision.reasons == ["Фото не проверены: не скачаны веса CLIP"]


@override_settings(MODERATION_CLIP_ENABLED=False)
def test_disabled_photo_check_does_not_block_approval(phones, models):
    models.images_error = "не должно вызываться"

    assert decide(submit(phones)).verdict == Verdict.APPROVED


def test_untrained_text_model_sends_to_moderator(phones, models):
    models.text_ready = False

    decision = decide(submit(phones))

    assert decision.verdict == Verdict.MANUAL
    assert decision.reasons[0].startswith("Текст не проверен")


def test_category_mismatch_is_explained(phones, models):
    models.text = {"phones-test": 0.05, "audio": 0.9, OTHER: 0.05}

    decision = decide(submit(phones))

    assert decision.verdict == Verdict.MANUAL
    assert decision.reasons == ["По тексту похоже на раздел «Аудио», а выбран «Телефоны»"]


def test_doubtful_photo_is_flagged(phones, models):
    models.photos = [0.95, 0.2]
    models.photo_label = "кошка"
    ad = submit(phones, photos=2)

    decision = decide(ad)

    second = ad.photos.order_by("position")[1]
    assert decision.verdict == Verdict.MANUAL
    assert decision.flagged_photos == {second.pk}
    assert decision.reasons == ["Фото 2 не похоже на технику: скорее «кошка», техника 20%"]


def test_review_flag_sends_to_moderator(phones, models):
    decision = decide(submit(phones, description="Только предоплата на карту, отправлю почтой."))

    assert decision.verdict == Verdict.MANUAL
    assert decision.reasons == ["Просьба о предоплате: «предоплата»"]


def test_submission_triggers_check_after_commit(phones, models, run_on_commit):
    with run_on_commit():
        ad = submit(phones)

    ad.refresh_from_db()
    check = ModerationCheck.objects.get(ad=ad)
    assert ad.status == AdStatus.ACTIVE
    assert ad.published_at is not None
    assert check.verdict == Verdict.APPROVED
    assert check.text_label == "phones-test"
    assert check.image_scores[0]["score"] == 0.95
    assert Notification.objects.filter(user=ad.seller, title__startswith="Объявление опубликовано")


def test_rejection_reaches_seller(phones, models, run_on_commit):
    with run_on_commit():
        ad = submit(phones, description="Пишите на почту seller@mail.ru, отвечу быстро.")

    ad.refresh_from_db()
    assert ad.status == AdStatus.REJECTED
    assert ad.rejection_reason.startswith("В описании есть контакты или ссылки")
    notification = Notification.objects.get(user=ad.seller)
    assert notification.title.startswith("Объявление отклонено")


def test_manual_verdict_queues_ad_and_flags_photos(phones, models, run_on_commit):
    models.photos = [0.1]
    with run_on_commit():
        ad = submit(phones)

    ad.refresh_from_db()
    assert ad.status == AdStatus.PENDING
    assert ad.review_queued_at is not None
    assert not ad.is_checking
    assert AdPhoto.objects.get(ad=ad).is_flagged


def test_stale_check_is_discarded(phones, models, monkeypatch):
    ad = submit(phones)
    original = pipeline.inspect

    def edited_meanwhile(target):
        result = original(target)
        ads_services.withdraw(target)
        return result

    monkeypatch.setattr(pipeline, "inspect", edited_meanwhile)

    assert run_auto_check(ad.pk) is None
    assert not ModerationCheck.objects.filter(ad=ad).exists()


def test_active_ads_are_not_rechecked(phones, models):
    ad = publish(phones)

    assert run_auto_check(ad.pk) is None


def test_substantial_edit_reruns_check(phones, models, run_on_commit):
    ad = publish(phones)
    models.text = {"phones-test": 0.02, OTHER: 0.98}
    models.photos = [0.05]

    with run_on_commit():
        ads_services.update_ad(
            ad,
            ads_services.AdDraft(
                fields={"description": "Отдам куртку зимнюю, почти новая, размер 50."},
                photos=list(ad.photos.all()),
            ),
        )

    ad.refresh_from_db()
    assert ad.status == AdStatus.REJECTED
    assert ModerationCheck.objects.filter(ad=ad, verdict=Verdict.REJECTED).exists()


def test_archived_ad_edited_then_restored_goes_through_check(phones, models, run_on_commit):
    ad = publish(phones)
    ads_services.withdraw(ad)
    ads_services.update_ad(
        ad,
        ads_services.AdDraft(
            fields={"description": "Совсем другое описание, теперь с новыми подробностями."},
            photos=list(ad.photos.all()),
        ),
    )

    with run_on_commit():
        ads_services.restore(ad)

    assert ModerationCheck.objects.filter(ad=ad).exists()


def test_my_ads_row_polls_while_checking(client, phones):
    ad = submit(phones)
    client.force_login(ad.seller)

    row = client.get(f"/my/ads/{ad.pk}/row/").content.decode()

    assert "Идёт автоматическая проверка" in row
    assert 'hx-trigger="every 3s"' in row
