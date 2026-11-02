# Второй заряд

Площадка объявлений о новой и б/у электронике для Владивостока, Приморья и Дальнего Востока.

## Стек

Python 3.12+, Django 5.2, PostgreSQL 16, Redis, Django Channels (daphne), Celery, htmx.
Страницы собираются шаблонами Django, динамика — через htmx и небольшие ES-модули без фреймворков.

## Запуск для разработки

Нужны Python 3.12+ и Docker (или локально установленные PostgreSQL 16 и Redis).

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
docker compose up -d
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Сайт: http://localhost:8000, админка: http://localhost:8000/control-panel/ (адрес задаётся `ADMIN_URL` в `.env`).
В режиме разработки есть страница с компонентами интерфейса: http://localhost:8000/dev/ui/.

В режиме разработки фоновые задачи по умолчанию выполняются сразу, без воркера (`CELERY_TASK_ALWAYS_EAGER=True` в `.env`), а письма печатаются в консоль `runserver`. Чтобы проверить работу через очередь, поставьте `False` и запустите воркер:

```bash
celery -A config worker -l info
celery -A config beat -l info
```

WebSocket (уведомления в реальном времени) работает и под `runserver`: в проекте подключён daphne.

## Проверки

```bash
pytest
ruff check .
ruff format --check .
```

Тесты работают с PostgreSQL: пользователю базы нужно право `CREATEDB` (в контейнере из `docker-compose.yml` оно есть).

## Структура

```
config/            настройки (base, dev, prod, test), urls, ASGI/WSGI, Celery
apps/core/         общие модели и города, middleware, фильтры шаблонов, статические страницы, ошибки
apps/accounts/     пользователь, регистрация, подтверждение почты, профиль, блокировки
apps/notifications/ уведомления на сайте, по почте и через WebSocket
templates/         base.html → layouts/ → страницы; components/ — общие части интерфейса
static/css/        tokens.css (дизайн-токены, светлая и тёмная тема), base, components, pages
static/js/         app.js и модули: меню, окна, вкладки, уведомления, тема
```

Бизнес-логика живёт в `services.py` (изменение данных) и `selectors.py` (выборки), представления остаются тонкими.

## Служебные адреса

- `/health/` — состояние базы и кеша (JSON, 503 при сбое);
- `/sitemap.xml`, `/robots.txt`;
- `/ws/notifications/` — WebSocket личных событий пользователя.

## Ограничение частоты запросов

Вход, регистрация, восстановление пароля, повторная отправка письма и смена почты ограничены по IP или пользователю (счётчики в кеше, `apps/core/ratelimit.py`). За nginx нужно указать `CLIENT_IP_HEADER=HTTP_X_REAL_IP`, иначе все запросы будут считаться с одного адреса.

## Лицензии ресурсов

Шрифт Manrope — SIL Open Font License 1.1 (`static/fonts/OFL-Manrope.txt`).
Иконки Lucide — ISC (`static/icons/LICENSE-lucide.txt`).
