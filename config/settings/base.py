from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])
SITE_URL = env("SITE_URL", default="http://localhost:8000").rstrip("/")
ADMIN_URL = env("ADMIN_URL", default="control-panel/")

SITE_NAME = "Второй заряд"
SITE_SLOGAN = "Новое и с историей\u00a0— честно и по делу"

INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sitemaps",
    "django.contrib.humanize",
    "django.contrib.postgres",
    "django.forms",
    "channels",
    "django_htmx",
    "apps.core",
    "apps.accounts",
    "apps.notifications",
    "apps.catalog",
    "apps.ads",
    "apps.moderation",
    "apps.chat",
    "apps.payments",
    "apps.reviews",
    "apps.support",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "apps.core.middleware.CurrentCityMiddleware",
    "apps.accounts.middleware.BannedUserMiddleware",
    "apps.accounts.middleware.LastSeenMiddleware",
    "apps.core.middleware.HtmxMessagesMiddleware",
    "apps.core.middleware.RateLimitMiddleware",
]

CLIENT_IP_HEADER = env("CLIENT_IP_HEADER", default="")

SMARTCAPTCHA_CLIENT_KEY = env("SMARTCAPTCHA_CLIENT_KEY", default="")
SMARTCAPTCHA_SERVER_KEY = env("SMARTCAPTCHA_SERVER_KEY", default="")

YOOKASSA_SHOP_ID = env("YOOKASSA_SHOP_ID", default="")
YOOKASSA_SECRET_KEY = env("YOOKASSA_SECRET_KEY", default="")
YOOKASSA_CHECK_WEBHOOK_IP = env.bool("YOOKASSA_CHECK_WEBHOOK_IP", default=True)

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.site",
                "apps.notifications.context_processors.notifications",
                "apps.ads.context_processors.compare",
                "apps.moderation.context_processors.moderation",
                "apps.chat.context_processors.messages",
            ],
            "builtins": ["apps.core.templatetags.ui"],
        },
    },
]

FORM_RENDERER = "apps.core.forms.FormRenderer"

DATABASES = {"default": env.db("DATABASE_URL")}
DATABASES["default"]["CONN_MAX_AGE"] = env.int("CONN_MAX_AGE", default=60)
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("CACHE_REDIS_URL", default="redis://localhost:6379/1"),
        "KEY_PREFIX": "vz",
    }
}

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [
                {
                    "address": env("CHANNELS_REDIS_URL", default="redis://localhost:6379/2"),
                    "socket_timeout": 30,
                }
            ]
        },
    }
}

CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://localhost:6379/0")
CELERY_TASK_IGNORE_RESULT = True
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TIMEZONE = "Asia/Vladivostok"
CELERY_BEAT_SCHEDULE = {
    "archive-stale-ads": {"task": "apps.ads.tasks.archive_stale_ads", "schedule": 60 * 60},
    "remove-orphan-photos": {
        "task": "apps.ads.tasks.remove_orphan_photos",
        "schedule": 6 * 60 * 60,
    },
    "recalculate-price-stats": {
        "task": "apps.ads.tasks.recalculate_price_stats",
        "schedule": 60 * 60,
    },
    "check-saved-searches": {"task": "apps.ads.tasks.check_saved_searches", "schedule": 60 * 60},
    "email-unread-messages": {"task": "apps.chat.tasks.email_unread_messages", "schedule": 5 * 60},
    "expire-promotions": {"task": "apps.payments.tasks.expire_promotions", "schedule": 15 * 60},
    "sync-pending-payments": {
        "task": "apps.payments.tasks.sync_pending_payments",
        "schedule": 10 * 60,
    },
}

AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "ads:home"
LOGOUT_REDIRECT_URL = "ads:home"
PASSWORD_RESET_TIMEOUT = 60 * 60 * 24 * 3
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

SESSION_ENGINE = "django.contrib.sessions.backends.cached_db"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 30

LANGUAGE_CODE = "ru"
TIME_ZONE = "Asia/Vladivostok"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = Path(env.str("STATIC_ROOT", default=str(BASE_DIR / "staticfiles")))
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(env.str("MEDIA_ROOT", default=str(BASE_DIR / "media")))
PROTECTED_MEDIA_ROOT = Path(env.str("PROTECTED_MEDIA_ROOT", default=str(BASE_DIR / "protected")))
PROTECTED_MEDIA_ACCEL_PREFIX = env.str("PROTECTED_MEDIA_ACCEL_PREFIX", default="")
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    "protected": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
        "OPTIONS": {"location": PROTECTED_MEDIA_ROOT, "base_url": None},
    },
}

EMAIL_CONFIG = env.email_url("EMAIL_URL", default="consolemail://")
vars().update(EMAIL_CONFIG)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="Второй заряд <noreply@vtoroy-zaryad.ru>")
SERVER_EMAIL = DEFAULT_FROM_EMAIL
SUPPORT_EMAIL = env("SUPPORT_EMAIL", default="support@vtoroy-zaryad.ru")
ADMINS = [("Admin", email) for email in env.list("ADMINS", default=[])]

MESSAGE_TAGS = {40: "error"}

ML_MODELS_DIR = Path(env.str("ML_MODELS_DIR", default=str(BASE_DIR / "var" / "models")))
MODERATION_TEXT_MODEL = ML_MODELS_DIR / "text-classifier.joblib"
MODERATION_CLIP_ENABLED = env.bool("MODERATION_CLIP_ENABLED", default=True)
MODERATION_CLIP_MODEL = env.str("MODERATION_CLIP_MODEL", default="ViT-B-32")
MODERATION_CLIP_WEIGHTS = env.str("MODERATION_CLIP_WEIGHTS", default="laion2b_s34b_b79k")
MODERATION_CLIP_DIR = ML_MODELS_DIR / "clip"
MODERATION_CLIP_THREADS = env.int("MODERATION_CLIP_THREADS", default=2)
MODERATION_THRESHOLDS = {
    "text_electronics": env.float("MODERATION_TEXT_ELECTRONICS", default=0.75),
    "text_other": env.float("MODERATION_TEXT_OTHER", default=0.85),
    "category_min": env.float("MODERATION_CATEGORY_MIN", default=0.2),
    "photo_electronics": env.float("MODERATION_PHOTO_ELECTRONICS", default=0.6),
    "photo_other": env.float("MODERATION_PHOTO_OTHER", default=0.3),
}

CSRF_FAILURE_VIEW = "apps.core.views.csrf_failure"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {"format": "{asctime} {levelname} {name}: {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "default"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.db.backends": {"level": "WARNING"},
    },
}
