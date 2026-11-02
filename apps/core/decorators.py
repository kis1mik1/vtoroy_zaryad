from functools import wraps

from .ratelimit import Rate, client_ip, hit


def ratelimit(scope: str, rate: Rate, *, key: str = "ip", methods=("POST",)):
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if request.method in methods:
                ident = (
                    f"user:{request.user.pk}"
                    if key == "user" and request.user.is_authenticated
                    else f"ip:{client_ip(request)}"
                )
                hit(scope, ident, rate)
            return view(request, *args, **kwargs)

        return wrapper

    return decorator
