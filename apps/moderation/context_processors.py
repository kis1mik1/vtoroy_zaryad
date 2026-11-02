from django.utils.functional import SimpleLazyObject

from .permissions import is_moderator
from .selectors import counters


def moderation(request):
    if not is_moderator(getattr(request, "user", None)):
        return {}
    return {"moderation_counts": SimpleLazyObject(counters)}
