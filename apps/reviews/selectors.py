from django.db.models import Count

from .models import RATING_LABELS, Review


def reviews_about(user, *, role: str = "", include_hidden: bool = False):
    queryset = Review.objects.filter(target=user).select_related("author", "target", "ad")
    if not include_hidden:
        queryset = queryset.visible()
    if role:
        queryset = queryset.filter(author_role=role)
    return queryset


def rating_distribution(user) -> list[dict]:
    counts = dict(
        Review.objects.visible()
        .filter(target=user)
        .values("rating")
        .annotate(total=Count("pk"))
        .values_list("rating", "total")
    )
    total = sum(counts.values())
    return [
        {
            "stars": stars,
            "label": RATING_LABELS[stars],
            "count": counts.get(stars, 0),
            "percent": round(100 * counts.get(stars, 0) / total) if total else 0,
        }
        for stars in range(5, 0, -1)
    ]


def reported_reviews():
    return (
        Review.objects.reported().select_related("author", "target", "ad").order_by("reported_at")
    )


def hidden_reviews():
    return (
        Review.objects.filter(is_hidden=True)
        .select_related("author", "target", "ad", "moderated_by")
        .order_by("-moderated_at")
    )
