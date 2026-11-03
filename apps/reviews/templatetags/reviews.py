from django import template

from apps.reviews import selectors, services

register = template.Library()

LATEST_ON_PROFILE = 3


@register.inclusion_tag("reviews/partials/conversation_action.html", takes_context=True)
def review_action(context, conversation):
    user = context["request"].user
    review = services.existing_review(user, conversation)
    return {
        "conversation": conversation,
        "review": review,
        "can_review": review is None and services.can_review(user, conversation),
    }


@register.inclusion_tag("reviews/partials/summary.html", takes_context=True)
def reviews_summary(context, person):
    return {
        "person": person,
        "distribution": selectors.rating_distribution(person) if person.rating_count else [],
        "latest": list(selectors.reviews_about(person)[:LATEST_ON_PROFILE]),
        "request": context["request"],
    }
