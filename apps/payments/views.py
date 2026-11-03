import json
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.accounts.decorators import verified_email_required
from apps.ads.models import Ad
from apps.core.ratelimit import client_ip

from . import gateway, selectors, services, tasks
from .models import Payment

logger = logging.getLogger(__name__)

PAGE_SIZE = 20


@verified_email_required
@require_http_methods(["GET", "POST"])
def promote(request, pk):
    ad = get_object_or_404(
        Ad.objects.alive().select_related("city").prefetch_related("photos"),
        pk=pk,
        seller=request.user,
    )
    if request.method == "POST":
        tariff = selectors.active_tariffs().filter(code=request.POST.get("tariff")).first()
        if tariff is None:
            messages.error(request, "Выберите тариф.")
            return redirect("payments:promote", pk=ad.pk)
        try:
            payment = services.start_payment(
                ad, request.user, tariff, site_url=request.build_absolute_uri("/").rstrip("/")
            )
        except (services.PaymentError, gateway.GatewayError) as exc:
            messages.error(request, str(exc))
            return redirect("payments:promote", pk=ad.pk)
        if not payment.is_pending:
            return redirect("payments:return", pk=payment.pk)
        return redirect(payment.confirmation_url)

    can_promote = True
    try:
        services.ensure_can_promote(ad, request.user)
    except services.PaymentError:
        can_promote = False
    return render(
        request,
        "payments/promote.html",
        {
            "ad": ad,
            "tariffs": selectors.active_tariffs(),
            "payments": selectors.ad_payments(ad),
            "can_promote": can_promote,
            "configured": gateway.is_configured(),
            "test_shop": gateway.is_test_shop(),
            "breadcrumbs": [("Мои объявления", reverse("ads:my_ads")), ("Продвижение", None)],
        },
    )


def _checked(request, pk) -> tuple[Payment, bool]:
    payment = get_object_or_404(
        Payment.objects.select_related("ad", "tariff"), pk=pk, user=request.user
    )
    try:
        return services.sync_payment(payment), True
    except gateway.GatewayError:
        return payment, False


@login_required
@require_GET
def payment_return(request, pk):
    payment, reachable = _checked(request, pk)
    return render(
        request,
        "payments/return.html",
        {
            "payment": payment,
            "reachable": reachable,
            "breadcrumbs": [
                ("Платежи", reverse("payments:history")),
                (f"Платёж № {payment.pk}", None),
            ],
        },
    )


@login_required
@require_GET
def payment_status(request, pk):
    payment, reachable = _checked(request, pk)
    return render(
        request, "payments/partials/status.html", {"payment": payment, "reachable": reachable}
    )


@login_required
@require_GET
def history(request):
    page = Paginator(selectors.user_payments(request.user), PAGE_SIZE).get_page(
        request.GET.get("page")
    )
    return render(
        request,
        "payments/history.html",
        {"page_obj": page, "breadcrumbs": [("Платежи", None)]},
    )


@csrf_exempt
@require_POST
def webhook(request):
    ip = client_ip(request)
    if settings.YOOKASSA_CHECK_WEBHOOK_IP and not gateway.is_trusted_ip(ip):
        logger.warning("ЮKassa: уведомление с чужого адреса %s отклонено", ip)
        return HttpResponseForbidden()
    try:
        provider_id = json.loads(request.body)["object"]["id"]
    except (ValueError, KeyError, TypeError):
        return HttpResponseBadRequest()
    payment = Payment.objects.filter(provider_payment_id=str(provider_id)).first()
    if payment is not None and payment.is_pending:
        tasks.sync_payment.delay(payment.pk)
    return HttpResponse()
