from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Category
from .selectors import clear_catalog_cache


@receiver(post_save, sender=Category)
@receiver(post_delete, sender=Category)
def reset_catalog_cache(**kwargs):
    clear_catalog_cache()
