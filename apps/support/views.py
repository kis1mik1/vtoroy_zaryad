from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods

from apps.core.decorators import ratelimit
from apps.core.ratelimit import Rate, client_ip

from . import selectors, services
from .forms import ContactForm
from .models import TicketTopic

CONTACT_RATE = Rate(limit=5, period=60 * 60)
SENT_SESSION_KEY = "support_ticket"


def _crumbs(*items):
    return [("Помощь", reverse("support:faq")), *[(label, None) for label in items]]


@require_GET
def faq(request):
    query = request.GET.get("q", "").strip()
    context = {
        "query": query,
        "results": selectors.search_faq(query) if query else None,
        "sections": selectors.faq_sections(),
    }
    if request.htmx and request.htmx.target == "faq-results":
        return render(request, "support/partials/faq_results.html", context)
    context["breadcrumbs"] = [("Помощь", None)]
    return render(request, "support/faq.html", context)


@require_http_methods(["GET", "POST"])
@ratelimit("support", CONTACT_RATE)
def contact(request):
    initial = {}
    if request.GET.get("topic") in TicketTopic.values:
        initial["topic"] = request.GET["topic"]
    form = ContactForm(
        request.POST or None, initial=initial, user=request.user, ip=client_ip(request)
    )
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        ticket = services.create_ticket(
            user=request.user,
            name=data["name"],
            email=data["email"],
            topic=data["topic"],
            subject=data["subject"],
            message=data["message"],
        )
        request.session[SENT_SESSION_KEY] = ticket.pk
        return redirect("support:contact_sent")
    return render(
        request,
        "support/contact.html",
        {"form": form, "breadcrumbs": _crumbs("Обращение в поддержку")},
        status=400 if request.method == "POST" else 200,
    )


@require_GET
def contact_sent(request):
    ticket_id = request.session.get(SENT_SESSION_KEY)
    if ticket_id is None:
        return redirect("support:faq")
    return render(
        request,
        "support/sent.html",
        {"ticket_id": ticket_id, "breadcrumbs": _crumbs("Обращение отправлено")},
    )


@login_required
@require_GET
def tickets(request):
    return render(
        request,
        "support/tickets.html",
        {"tickets": selectors.tickets_for(request.user), "breadcrumbs": _crumbs("Мои обращения")},
    )
