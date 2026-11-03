from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.db.models import Prefetch, Q

from .models import FAQItem, FAQSection, SupportTicket, TicketReply

MIN_QUERY = 2


def published_items():
    return FAQItem.objects.filter(is_published=True, section__is_published=True).select_related(
        "section"
    )


def faq_sections() -> list[FAQSection]:
    return list(
        FAQSection.objects.filter(is_published=True).prefetch_related(
            Prefetch(
                "items",
                queryset=FAQItem.objects.filter(is_published=True).order_by("sort_order", "pk"),
                to_attr="published",
            )
        )
    )


def search_faq(query: str) -> list[FAQItem]:
    query = query.strip()
    if len(query) < MIN_QUERY:
        return []
    vector = SearchVector("question", weight="A", config="russian") + SearchVector(
        "answer", weight="B", config="russian"
    )
    search = SearchQuery(query, config="russian", search_type="websearch")
    found = list(
        published_items()
        .annotate(document=vector, rank=SearchRank(vector, search))
        .filter(document=search)
        .order_by("-rank", "section__sort_order", "sort_order")
    )
    if found:
        return found
    words = [word for word in query.split() if len(word) >= MIN_QUERY]
    condition = Q()
    for word in words:
        condition &= Q(question__icontains=word) | Q(answer__icontains=word)
    return list(published_items().filter(condition)) if words else []


def tickets_for(user):
    return SupportTicket.objects.filter(user=user).prefetch_related(
        Prefetch("replies", queryset=TicketReply.objects.order_by("created_at"))
    )
