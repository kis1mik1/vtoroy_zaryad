import json
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render

VERIFY_REQUIRED_MESSAGE = "Подтвердите почту, чтобы пользоваться этой функцией."


def verified_email_required(view):
    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if request.user.is_email_verified:
            return view(request, *args, **kwargs)
        if request.htmx:
            response = HttpResponse(status=403)
            response["HX-Trigger"] = json.dumps(
                {"toast": {"level": "warning", "text": VERIFY_REQUIRED_MESSAGE}},
            )
            return response
        return render(request, "accounts/verify_required.html", status=403)

    return wrapper
