from django.conf import settings
from django.shortcuts import render
from django.urls import reverse

from .services import touch_last_seen

BANNED_ALLOWED_PREFIXES = ("/static/", "/media/")
BANNED_ALLOWED_NAMES = (
    "accounts:logout",
    "core:rules",
    "core:terms",
    "core:privacy",
    "core:safety",
)


class LastSeenMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            touch_last_seen(request.user)
        return self.get_response(request)


class BannedUserMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self._allowed_paths = None

    def allowed_paths(self):
        if self._allowed_paths is None:
            self._allowed_paths = {reverse(name) for name in BANNED_ALLOWED_NAMES}
            self._allowed_paths.add(f"/{settings.ADMIN_URL}logout/")
        return self._allowed_paths

    def __call__(self, request):
        user = request.user
        if (
            user.is_authenticated
            and user.is_banned
            and not request.path.startswith(BANNED_ALLOWED_PREFIXES)
            and request.path not in self.allowed_paths()
        ):
            return render(request, "accounts/banned.html", {"banned_user": user}, status=403)
        return self.get_response(request)
