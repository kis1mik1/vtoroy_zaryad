RECENT_KEY = "recent_ads"
COMPARE_KEY = "compare_ads"
RECENT_LIMIT = 12
COMPARE_LIMIT = 3


def _ids(request, key) -> list[int]:
    return [int(pk) for pk in request.session.get(key, []) if str(pk).isdigit()]


def remember_view(request, ad_id: int) -> None:
    ids = [pk for pk in _ids(request, RECENT_KEY) if pk != ad_id]
    request.session[RECENT_KEY] = [ad_id, *ids][:RECENT_LIMIT]


def recent_ids(request, exclude: int | None = None) -> list[int]:
    return [pk for pk in _ids(request, RECENT_KEY) if pk != exclude]


def compare_ids(request) -> list[int]:
    return _ids(request, COMPARE_KEY)[:COMPARE_LIMIT]


class CompareFull(Exception):
    pass


def toggle_compare(request, ad_id: int) -> bool:
    ids = compare_ids(request)
    if ad_id in ids:
        ids.remove(ad_id)
        added = False
    else:
        if len(ids) >= COMPARE_LIMIT:
            raise CompareFull
        ids.append(ad_id)
        added = True
    request.session[COMPARE_KEY] = ids
    return added


def set_compare(request, ids: list[int]) -> None:
    request.session[COMPARE_KEY] = ids[:COMPARE_LIMIT]
