from django.conf import settings

THEMES = ("light", "dark")


def site(request):
    theme = request.COOKIES.get("theme")
    return {
        "project_name": settings.SITE_NAME,
        "site_slogan": settings.SITE_SLOGAN,
        "site_url": settings.SITE_URL,
        "support_email": settings.SUPPORT_EMAIL,
        "current_city": getattr(request, "city", None),
        "theme": theme if theme in THEMES else "",
    }
