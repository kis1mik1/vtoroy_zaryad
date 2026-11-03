from .base import *  # noqa: F403
from .base import STORAGES, env

DEBUG = env.bool("DEBUG", default=False)

STORAGES = {
    **STORAGES,
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"},
}

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
SESSION_COOKIE_HTTPONLY = True
X_FRAME_OPTIONS = "DENY"

CLIENT_IP_HEADER = env("CLIENT_IP_HEADER", default="HTTP_X_REAL_IP")
PROTECTED_MEDIA_ACCEL_PREFIX = env.str(
    "PROTECTED_MEDIA_ACCEL_PREFIX", default="/protected-internal/"
)
