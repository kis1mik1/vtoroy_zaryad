from functools import partial

import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def user(db):
    from apps.accounts.tests.factories import UserFactory

    return UserFactory()


@pytest.fixture
def auth_client(client, user):
    client.force_login(user)
    return client


@pytest.fixture
def run_on_commit(django_capture_on_commit_callbacks):
    return partial(django_capture_on_commit_callbacks, execute=True)
