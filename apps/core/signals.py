from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import City
from .selectors import clear_cities_cache


@receiver(post_save, sender=City)
@receiver(post_delete, sender=City)
def reset_cities_cache(**kwargs):
    clear_cities_cache()
