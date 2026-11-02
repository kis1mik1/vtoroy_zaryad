from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.accounts.decorators import verified_email_required
from apps.ads.models import Ad, AdStatus
from apps.core.decorators import ratelimit
from apps.core.ratelimit import Rate

from . import selectors, services
from .forms import BanForm, ComplaintForm, RejectForm
from .models import AD_COMPLAINT_REASONS, USER_COMPLAINT_REASONS, ComplaintStatus
from .permissions import BAN_USER, HANDLE_COMPLAINT, REVIEW_AD, permission_required

PAGE_SIZE = 20
HISTORY_PAGE_SIZE = 50
COMPLAINT_RATE = Rate(limit=20, period=24 * 60 * 60)
COMPLAINT_SENT = "Жалоба отправлена. Модератор разберётся в течение рабочего дня."

User = get_user_model()


def _crumbs(*items) -> list:
    return [("Модерация", reverse("moderation:queue")), *[(label, None) for label in items]]


def _panel(request, template: str, context: dict, status: int = 200):
    context.setdefault("models_status", selectors.models_status())
    return render(request, template, context, status=status)


@permission_required(REVIEW_AD)
@require_GET
def queue(request):
    page = Paginator(selectors.review_queue(), PAGE_SIZE).get_page(request.GET.get("page"))
    return _panel(
        request,
        "moderation/queue.html",
        {
            "page_obj": page,
            "stats": selectors.today_stats(),
            "section": "queue",
            "breadcrumbs": [("Модерация", None)],
        },
    )


@permission_required(REVIEW_AD)
@require_GET
def rejected(request):
    page = Paginator(selectors.auto_rejected(), PAGE_SIZE).get_page(request.GET.get("page"))
    return _panel(
        request,
        "moderation/rejected.html",
        {
            "page_obj": page,
            "section": "rejected",
            "breadcrumbs": _crumbs("Отклонены автоматически"),
        },
    )


@permission_required(REVIEW_AD)
@require_GET
def history(request):
    paginator = Paginator(selectors.recent_actions(), HISTORY_PAGE_SIZE)
    page = paginator.get_page(request.GET.get("page"))
    return _panel(
        request,
        "moderation/history.html",
        {
            "page_obj": page,
            "section": "history",
            "breadcrumbs": _crumbs("Журнал решений"),
        },
    )


def _initial_reason(check) -> str:
    if check is None:
        return ""
    return next((flag["reason"] for flag in check.rule_flags if flag.get("reason")), "")


def _review_context(request, ad: Ad, form: RejectForm | None = None) -> dict:
    check = ad.check_list[0] if ad.check_list else None
    if form is None:
        form = RejectForm(initial={"reason": _initial_reason(check)})
    return {
        "ad": ad,
        "check": check,
        "form": form,
        "history": selectors.ad_history(ad),
        "complaints": list(ad.complaints.select_related("author").order_by("-created_at")),
        "seller_summary": selectors.user_summary(ad.seller),
        "section": "queue" if ad.status == AdStatus.PENDING else None,
        "breadcrumbs": _crumbs(f"Объявление № {ad.pk}"),
    }


@permission_required(REVIEW_AD)
@require_GET
def ad_review(request, pk):
    try:
        ad = selectors.ad_for_review(pk)
    except Ad.DoesNotExist as exc:
        raise Http404 from exc
    return _panel(request, "moderation/ad_review.html", _review_context(request, ad))


def _next_in_queue(after: Ad) -> str:
    following = selectors.review_queue().exclude(pk=after.pk).first()
    if following is None:
        return reverse("moderation:queue")
    return reverse("moderation:ad", args=[following.pk])


@permission_required(REVIEW_AD)
@require_POST
def ad_decide(request, pk):
    ad = get_object_or_404(Ad.objects.alive(), pk=pk)
    decision = request.POST.get("decision")
    if decision not in ("approve", "reject"):
        return HttpResponseBadRequest("Неизвестное решение.")
    try:
        if decision == "approve":
            services.approve(ad, request.user)
            messages.success(request, f"Объявление № {ad.pk} опубликовано")
        else:
            form = RejectForm(request.POST)
            if not form.is_valid():
                context = _review_context(request, selectors.ad_for_review(pk), form)
                return _panel(request, "moderation/ad_review.html", context, status=400)
            services.reject(
                ad, request.user, form.cleaned_data["reason"], form.cleaned_data["comment"]
            )
            messages.success(request, f"Объявление № {ad.pk} отклонено, продавец получил причину")
    except services.ModerationError as exc:
        messages.error(request, str(exc))
        return redirect("moderation:ad", pk=ad.pk)
    if request.POST.get("next") == "rejected":
        return redirect("moderation:rejected")
    return redirect(_next_in_queue(ad))


@permission_required(HANDLE_COMPLAINT)
@require_GET
def complaints(request):
    status = request.GET.get("status", ComplaintStatus.NEW)
    if status not in ComplaintStatus.values:
        status = ComplaintStatus.NEW
    return _panel(
        request,
        "moderation/complaints.html",
        {
            "groups": selectors.complaint_groups(status),
            "status": status,
            "statuses": ComplaintStatus.choices,
            "section": "complaints",
            "breadcrumbs": _crumbs("Жалобы"),
        },
    )


@permission_required(HANDLE_COMPLAINT)
@require_POST
def complaints_dismiss(request, kind, pk):
    if kind == "ad":
        count = services.dismiss_complaints(request.user, ad=get_object_or_404(Ad, pk=pk))
    elif kind == "user":
        count = services.dismiss_complaints(request.user, user=get_object_or_404(User, pk=pk))
    else:
        return HttpResponseBadRequest("Неизвестный тип жалобы.")
    messages.success(request, f"Жалобы отклонены: {count}")
    return redirect("moderation:complaints")


def _user_context(request, person, form: BanForm | None = None) -> dict:
    return {
        "person": person,
        "summary": selectors.user_summary(person),
        "bans": person.ban_records.select_related("moderator", "lifted_by"),
        "complaints": selectors.user_complaints(person)[:30],
        "ads": selectors.user_ads(person)[:20],
        "form": form or BanForm(),
        "can_ban": request.user.has_perm(BAN_USER),
        "breadcrumbs": _crumbs(person.first_name or person.email),
    }


@permission_required(REVIEW_AD)
@require_GET
def user_card(request, pk):
    person = get_object_or_404(User, pk=pk)
    return _panel(request, "moderation/user.html", _user_context(request, person))


@permission_required(BAN_USER)
@require_POST
def user_ban(request, pk):
    person = get_object_or_404(User, pk=pk)
    form = BanForm(request.POST)
    if not form.is_valid():
        return _panel(request, "moderation/user.html", _user_context(request, person, form), 400)
    try:
        services.ban(person, request.user, reason=form.reason_text, until=form.until)
    except services.ModerationError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"{person.first_name} заблокирован(а)")
    return redirect("moderation:user", pk=person.pk)


@permission_required(BAN_USER)
@require_POST
def user_unban(request, pk):
    person = get_object_or_404(User, pk=pk)
    try:
        services.lift_ban(person, request.user)
    except services.ModerationError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Блокировка снята")
    return redirect("moderation:user", pk=person.pk)


def _complain(request, *, ad=None, person=None):
    if ad is not None:
        reasons, target_url = AD_COMPLAINT_REASONS, reverse("ads:detail", args=[ad.pk, ad.slug])
    else:
        reasons, target_url = USER_COMPLAINT_REASONS, reverse("ads:profile", args=[person.pk])
    form = ComplaintForm(request.POST if request.method == "POST" else None, reasons=reasons)
    error = ""
    if request.method == "POST" and form.is_valid():
        try:
            services.file_complaint(
                request.user,
                ad=ad,
                user=person,
                reason=form.cleaned_data["reason"],
                comment=form.cleaned_data["comment"],
            )
        except services.ModerationError as exc:
            error = str(exc)
        else:
            if request.htmx:
                return render(request, "moderation/partials/complaint_sent.html")
            messages.success(request, COMPLAINT_SENT)
            return redirect(target_url)
    context = {"form": form, "ad": ad, "person": person, "error": error, "target_url": target_url}
    template = "moderation/complaint.html"
    if request.htmx:
        template = "moderation/partials/complaint_form.html"
    return render(request, template, context, status=400 if request.method == "POST" else 200)


@verified_email_required
@require_http_methods(["GET", "POST"])
@ratelimit("complaint", COMPLAINT_RATE, key="user")
def complain_ad(request, pk):
    ad = get_object_or_404(Ad.objects.visible().select_related("seller"), pk=pk)
    return _complain(request, ad=ad)


@verified_email_required
@require_http_methods(["GET", "POST"])
@ratelimit("complaint", COMPLAINT_RATE, key="user")
def complain_user(request, pk):
    person = get_object_or_404(User, pk=pk, is_active=True)
    return _complain(request, person=person)
