from .models import Notification


def unread_count(user) -> int:
    return Notification.objects.filter(user=user, is_read=False).count()


def recent_for(user, limit: int = 8):
    return list(Notification.objects.filter(user=user)[:limit])
