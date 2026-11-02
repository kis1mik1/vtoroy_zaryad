from datetime import timedelta

from django.core import signing

from .models import User

EMAIL_TOKEN_MAX_AGE = timedelta(days=3)
VERIFY_SALT = "accounts.verify-email"
CHANGE_SALT = "accounts.change-email"


class InvalidToken(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def make_verification_token(user: User) -> str:
    return signing.dumps({"uid": user.pk, "email": user.email}, salt=VERIFY_SALT, compress=True)


def make_email_change_token(user: User, new_email: str) -> str:
    payload = {"uid": user.pk, "old": user.email, "new": new_email}
    return signing.dumps(payload, salt=CHANGE_SALT, compress=True)


def _load(token: str, salt: str) -> dict:
    try:
        return signing.loads(token, salt=salt, max_age=EMAIL_TOKEN_MAX_AGE)
    except signing.SignatureExpired as exc:
        raise InvalidToken("Срок действия ссылки истёк. Запросите новое письмо.") from exc
    except signing.BadSignature as exc:
        raise InvalidToken("Ссылка повреждена. Скопируйте её из письма целиком.") from exc


def _user(uid) -> User:
    user = User.objects.filter(pk=uid, is_active=True).first()
    if user is None:
        raise InvalidToken("Аккаунт не найден или удалён.")
    return user


def read_verification_token(token: str) -> User:
    data = _load(token, VERIFY_SALT)
    user = _user(data.get("uid"))
    if user.email != data.get("email"):
        raise InvalidToken("Ссылка выдана для другого адреса почты. Запросите новое письмо.")
    return user


def read_email_change_token(token: str) -> tuple[User, str]:
    data = _load(token, CHANGE_SALT)
    user = _user(data.get("uid"))
    if user.email != data.get("old"):
        raise InvalidToken("Адрес почты уже изменился. Запросите смену ещё раз.")
    return user, data["new"]
