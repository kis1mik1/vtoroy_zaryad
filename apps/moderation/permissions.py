from functools import wraps

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied
from django.db.models import Q

MODERATORS_GROUP = "Модераторы"
REVIEW_AD = "moderation.review_ad"
HANDLE_COMPLAINT = "moderation.handle_complaint"
BAN_USER = "moderation.ban_user"

GROUP_PERMISSIONS = (
    ("moderation", "review_ad"),
    ("moderation", "handle_complaint"),
    ("moderation", "ban_user"),
    ("moderation", "view_moderationcheck"),
    ("moderation", "view_moderationaction"),
    ("moderation", "view_complaint"),
    ("ads", "view_ad"),
    ("ads", "view_adphoto"),
    ("accounts", "view_user"),
    ("accounts", "view_banrecord"),
    ("reviews", "moderate_review"),
    ("reviews", "view_review"),
)


def ensure_moderators_group() -> Group:
    group, _ = Group.objects.get_or_create(name=MODERATORS_GROUP)
    query = Q()
    for app_label, codename in GROUP_PERMISSIONS:
        query |= Q(content_type__app_label=app_label, codename=codename)
    group.permissions.add(*Permission.objects.filter(query))
    return group


def is_moderator(user) -> bool:
    return bool(user and user.is_authenticated and user.has_perm(REVIEW_AD))


def permission_required(permission: str):
    def decorator(view):
        @login_required
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.has_perm(permission):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapper

    return decorator
