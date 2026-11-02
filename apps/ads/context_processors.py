from .session import compare_ids


def compare(request):
    if not hasattr(request, "session"):
        return {}
    return {"compare_count": len(compare_ids(request))}
