import json

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from . import services
from .models import Notification
from .selectors import recent_for

PAGE_SIZE = 20


@login_required
@require_GET
def notification_list(request):
    only_unread = request.GET.get("filter") == "unread"
    queryset = Notification.objects.filter(user=request.user)
    if only_unread:
        queryset = queryset.filter(is_read=False)
    page = Paginator(queryset, PAGE_SIZE).get_page(request.GET.get("page"))
    return render(
        request,
        "notifications/list.html",
        {
            "page_obj": page,
            "only_unread": only_unread,
            "total_count": Notification.objects.filter(user=request.user).count(),
            "breadcrumbs": [("Уведомления", None)],
        },
    )


@login_required
@require_GET
def notification_dropdown(request):
    return render(
        request,
        "notifications/partials/dropdown.html",
        {"notifications": recent_for(request.user)},
    )


@login_required
@require_GET
def notification_open(request, pk):
    notification = get_object_or_404(Notification, pk=pk, user=request.user)
    services.mark_read(notification)
    if notification.url and url_has_allowed_host_and_scheme(
        notification.url, allowed_hosts={request.get_host()}
    ):
        return HttpResponseRedirect(notification.url)
    return redirect("notifications:list")


@login_required
@require_POST
def notification_read_all(request):
    services.mark_all_read(request.user)
    if request.htmx:
        response = render(
            request,
            "notifications/partials/dropdown.html",
            {"notifications": recent_for(request.user), "unread_notifications": 0},
        )
        response["HX-Trigger"] = json.dumps({"notifications-count": 0})
        return response
    next_url = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        next_url = reverse("notifications:list")
    return HttpResponseRedirect(next_url)
