from django.db.models.signals import post_delete
from django.dispatch import receiver

from apps.accounts.signals import account_deleted

from . import services
from .models import AdPhoto
from .photos import delete_photo_files


@receiver(account_deleted)
def archive_ads_of_deleted_account(sender, user, **kwargs):
    services.archive_all_for_seller(user)


@receiver(post_delete, sender=AdPhoto)
def remove_photo_files(sender, instance, **kwargs):
    delete_photo_files(instance)
