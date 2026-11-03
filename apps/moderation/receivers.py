from functools import partial

from django.db import transaction
from django.db.models.signals import post_migrate
from django.dispatch import receiver

from apps.ads.signals import ad_submitted

from .permissions import ensure_moderators_group
from .tasks import check_ad


@receiver(ad_submitted)
def schedule_check(sender, ad, **kwargs):
    transaction.on_commit(partial(check_ad.delay, ad.pk))


@receiver(post_migrate)
def create_moderators_group(sender, **kwargs):
    if sender.name in ("apps.moderation", "apps.reviews"):
        ensure_moderators_group()
