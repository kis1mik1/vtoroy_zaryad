from .selectors import unread_count


def messages(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    return {"unread_messages": unread_count(user)}
