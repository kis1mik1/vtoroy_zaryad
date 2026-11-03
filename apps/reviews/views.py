from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.accounts.decorators import verified_email_required
from apps.chat import selectors as chat_selectors
from apps.moderation.permissions import permission_required

from . import selectors, services
from .forms import ROLE_FILTERS, HideForm, ReplyForm, ReportForm, ReviewForm
from .models import Review

PAGE_SIZE = 20
MODERATE_REVIEW = "reviews.moderate_review"

User = get_user_model()


def _form_page(request, form, *, conversation=None, review=None, status=200):
    target = review.target if review else conversation.other(request.user)
    ad = review.ad if review else conversation.ad
    return render(
        request,
        "reviews/form.html",
        {
            "form": form,
            "target": target,
            "ad": ad,
            "review": review,
            "back_url": reverse("reviews:list", args=[target.pk])
            if review
            else reverse("chat:conversation", args=[conversation.pk]),
            "breadcrumbs": [("Отзывы", reverse("reviews:list", args=[target.pk])), ("Отзыв", None)],
        },
        status=status,
    )


@verified_email_required
@require_http_methods(["GET", "POST"])
def create(request, conversation_pk):
    conversation = chat_selectors.conversation_for(request.user, conversation_pk)
    if conversation is None:
        raise Http404
    try:
        services.ensure_can_review(request.user, conversation)
    except services.ReviewError as exc:
        messages.error(request, str(exc))
        return redirect("chat:conversation", pk=conversation.pk)
    form = ReviewForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            review = services.create_review(request.user, conversation, **form.cleaned_data)
        except services.ReviewError as exc:
            messages.error(request, str(exc))
            return redirect("chat:conversation", pk=conversation.pk)
        messages.success(request, "Спасибо! Отзыв опубликован.")
        return redirect(services.reviews_url(review))
    status = 400 if request.method == "POST" else 200
    return _form_page(request, form, conversation=conversation, status=status)


@verified_email_required
@require_http_methods(["GET", "POST"])
def edit(request, pk):
    review = get_object_or_404(
        Review.objects.select_related("target", "ad"), pk=pk, author=request.user
    )
    if not review.is_editable:
        messages.error(request, "Отзыв, на который уже ответили, изменить нельзя.")
        return redirect(services.reviews_url(review))
    form = ReviewForm(request.POST or None, initial={"rating": review.rating, "text": review.text})
    if request.method == "POST" and form.is_valid():
        services.update_review(review, request.user, **form.cleaned_data)
        messages.success(request, "Отзыв изменён.")
        return redirect(services.reviews_url(review))
    status = 400 if request.method == "POST" else 200
    return _form_page(request, form, review=review, status=status)


@require_GET
def review_list(request, user_pk):
    person = get_object_or_404(
        User.objects.select_related("city"), pk=user_pk, is_active=True, deleted_at__isnull=True
    )
    role = request.GET.get("role", "")
    if role not in dict(ROLE_FILTERS):
        role = ""
    can_moderate = request.user.has_perm(MODERATE_REVIEW)
    reviews = selectors.reviews_about(person, role=role, include_hidden=can_moderate)
    page = Paginator(reviews, PAGE_SIZE).get_page(request.GET.get("page"))
    return render(
        request,
        "reviews/list.html",
        {
            "person": person,
            "page_obj": page,
            "role": role,
            "roles": ROLE_FILTERS,
            "distribution": selectors.rating_distribution(person),
            "can_moderate": can_moderate,
            "reply_form": ReplyForm(),
            "report_form": ReportForm(),
            "hide_form": HideForm(),
            "breadcrumbs": [
                (person.first_name, reverse("ads:profile", args=[person.pk])),
                ("Отзывы", None),
            ],
        },
    )


def _back(review: Review):
    return redirect(services.reviews_url(review))


@verified_email_required
@require_POST
def reply(request, pk):
    review = get_object_or_404(Review, pk=pk, target=request.user)
    form = ReplyForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Напишите ответ.")
        return _back(review)
    try:
        services.reply(review, request.user, form.cleaned_data["text"])
    except services.ReviewError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Ответ опубликован.")
    return _back(review)


@login_required
@require_POST
def report(request, pk):
    review = get_object_or_404(Review, pk=pk, target=request.user)
    form = ReportForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Опишите, что не так с отзывом.")
        return _back(review)
    try:
        services.report(review, request.user, form.cleaned_data["reason"])
    except services.ReviewError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Жалоба отправлена. Модератор проверит отзыв.")
    return _back(review)


@permission_required(MODERATE_REVIEW)
@require_GET
def moderation_list(request):
    hidden = request.GET.get("show") == "hidden"
    reviews = selectors.hidden_reviews() if hidden else selectors.reported_reviews()
    page = Paginator(reviews, PAGE_SIZE).get_page(request.GET.get("page"))
    return render(
        request,
        "reviews/moderation.html",
        {
            "page_obj": page,
            "hidden": hidden,
            "hide_form": HideForm(),
            "section": "reviews",
            "breadcrumbs": [("Модерация", reverse("moderation:queue")), ("Отзывы", None)],
        },
    )


def _after_moderation(request, review: Review):
    if request.POST.get("next") == "list":
        return _back(review)
    return redirect("reviews:moderation")


@permission_required(MODERATE_REVIEW)
@require_POST
def moderate(request, pk, action):
    review = get_object_or_404(Review, pk=pk)
    try:
        if action == "hide":
            form = HideForm(request.POST)
            if not form.is_valid():
                messages.error(request, "Укажите причину, по которой отзыв скрыт.")
                return _after_moderation(request, review)
            services.hide(review, request.user, form.cleaned_data["reason"])
            messages.success(request, "Отзыв скрыт, рейтинг пересчитан.")
        elif action == "restore":
            services.restore(review, request.user)
            messages.success(request, "Отзыв снова виден.")
        elif action == "keep":
            services.keep(review, request.user)
            messages.success(request, "Жалоба отклонена, отзыв остаётся.")
        else:
            return HttpResponseBadRequest("Неизвестное действие.")
    except services.ReviewError as exc:
        messages.error(request, str(exc))
    return _after_moderation(request, review)
