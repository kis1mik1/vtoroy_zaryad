from django.conf import settings
from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("city/", views.city_select, name="city_select"),
    path(
        "rules/",
        views.InfoPageView.as_view(
            template_name="core/pages/rules.html",
            title="Правила размещения",
            description="Что можно и что нельзя продавать на площадке и как оформить объявление.",
        ),
        name="rules",
    ),
    path(
        "safety/",
        views.InfoPageView.as_view(
            template_name="core/pages/safety.html",
            title="Безопасная сделка",
            description="Как проверить технику при встрече и не попасться мошенникам.",
        ),
        name="safety",
    ),
    path(
        "terms/",
        views.InfoPageView.as_view(
            template_name="core/pages/terms.html",
            title="Пользовательское соглашение",
            description="Условия использования площадки «Второй заряд».",
        ),
        name="terms",
    ),
    path(
        "privacy/",
        views.InfoPageView.as_view(
            template_name="core/pages/privacy.html",
            title="Политика конфиденциальности",
            description="Какие данные мы собираем, зачем и как их защищаем.",
        ),
        name="privacy",
    ),
    path(
        "about/",
        views.InfoPageView.as_view(
            template_name="core/pages/about.html",
            title="О проекте",
            description="Площадка объявлений о технике для Владивостока и Дальнего Востока.",
        ),
        name="about",
    ),
    path("robots.txt", views.robots_txt, name="robots"),
    path("health/", views.health, name="health"),
]

if settings.DEBUG:
    urlpatterns.append(path("dev/ui/", views.styleguide, name="styleguide"))
