from django.dispatch import receiver

from apps.accounts.signals import account_deleted

from .models import Conversation


@receiver(account_deleted)
def hide_conversations_of_deleted_account(sender, user, **kwargs):
    Conversation.objects.filter(buyer=user).update(buyer_hidden=True)
    Conversation.objects.filter(seller=user).update(seller_hidden=True)
