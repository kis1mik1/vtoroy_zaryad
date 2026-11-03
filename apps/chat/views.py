import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.decorators import verified_email_required
from apps.ads.models import Ad
from apps.core.decorators import ratelimit
from apps.core.ratelimit import Rate

from . import selectors, services
from .models import Message, UserBlock

UPLOAD_RATE = Rate(limit=60, period=60 * 60)


def _conversation(request, pk):
    conversation = selectors.conversation_for(request.user, pk)
    if conversation is None:
        raise Http404
    return conversation


def _error(request, text: str, status: int = 400) -> HttpResponse:
    response = HttpResponse(text, status=status, content_type="text/plain; charset=utf-8")
    response["HX-Trigger"] = json.dumps({"toast": {"level": "error", "text": text}})
    return response


def _message_html(request, message) -> HttpResponse:
    return render(
        request, "chat/partials/message.html", {"message": message, "viewer": request.user}
    )


@login_required
@require_GET
def conversation_list(request):
    return render(
        request,
        "chat/list.html",
        {
            "conversations": selectors.conversations_for(request.user),
            "breadcrumbs": [("Сообщения", None)],
        },
    )


@login_required
@require_GET
def conversation(request, pk):
    conversation = _conversation(request, pk)
    services.mark_read(conversation, request.user)
    other = conversation.other(request.user)
    blocked_by_me = UserBlock.objects.filter(user=request.user, blocked_user=other).exists()
    return render(
        request,
        "chat/conversation.html",
        {
            "conversation": conversation,
            "other": other,
            "history": selectors.history(conversation),
            "blocked_by_me": blocked_by_me,
            "blocked": blocked_by_me or services.is_blocked(request.user.pk, other.pk),
            "is_seller": request.user.pk == conversation.seller_id,
            "breadcrumbs": [("Сообщения", reverse("chat:list")), (other.first_name, None)],
        },
    )


@verified_email_required
@require_POST
def start(request, pk):
    ad = get_object_or_404(Ad.objects.visible(), pk=pk)
    try:
        conversation = services.start_conversation(ad, request.user)
    except services.ChatError as exc:
        messages.error(request, str(exc))
        return redirect("ads:detail", pk=ad.pk, slug=ad.slug)
    return redirect("chat:conversation", pk=conversation.pk)


@verified_email_required
@require_POST
def send(request, pk):
    conversation = _conversation(request, pk)
    try:
        message = services.send_text(conversation, request.user, request.POST.get("text", ""))
    except services.ChatError as exc:
        if request.htmx or request.headers.get("X-Requested-With"):
            return _error(request, str(exc))
        messages.error(request, str(exc))
        return redirect("chat:conversation", pk=pk)
    if request.htmx or request.headers.get("X-Requested-With"):
        return _message_html(request, message)
    return redirect("chat:conversation", pk=pk)


@verified_email_required
@require_POST
@ratelimit("chat-upload", UPLOAD_RATE, key="user")
def send_photo(request, pk):
    conversation = _conversation(request, pk)
    uploaded = request.FILES.get("photo")
    if uploaded is None:
        return _error(request, "Файл не получен.")
    try:
        message = services.send_photo(conversation, request.user, uploaded)
    except (services.ChatError, ValidationError) as exc:
        return _error(request, getattr(exc, "messages", [str(exc)])[0])
    return _message_html(request, message)


@verified_email_required
@require_POST
@ratelimit("chat-upload", UPLOAD_RATE, key="user")
def send_voice(request, pk):
    conversation = _conversation(request, pk)
    uploaded = request.FILES.get("voice")
    if uploaded is None:
        return _error(request, "Запись не получена.")
    try:
        services.send_voice(conversation, request.user, uploaded)
    except services.ChatError as exc:
        return _error(request, str(exc))
    return HttpResponse(status=202)


@login_required
@require_POST
def hide(request, pk):
    services.hide(_conversation(request, pk), request.user)
    messages.success(request, "Диалог скрыт. Он вернётся, если собеседник напишет снова.")
    return redirect("chat:list")


@login_required
@require_POST
def block(request, pk):
    conversation = _conversation(request, pk)
    other = conversation.other(request.user)
    if request.POST.get("action") == "unblock":
        services.unblock(request.user, other)
        messages.success(request, f"{other.first_name} снова может вам писать.")
    else:
        services.block(request.user, other)
        messages.success(request, f"{other.first_name} больше не сможет вам писать.")
    return redirect("chat:conversation", pk=pk)


@login_required
@require_GET
def message_file(request, pk):
    message = get_object_or_404(
        Message.objects.select_related("conversation").exclude(file=""), pk=pk, is_ready=True
    )
    if not message.conversation.is_participant(request.user):
        raise Http404
    if settings.PROTECTED_MEDIA_ACCEL_PREFIX:
        response = HttpResponse()
        response["X-Accel-Redirect"] = f"{settings.PROTECTED_MEDIA_ACCEL_PREFIX}{message.file.name}"
        response["Content-Type"] = ""
    else:
        response = FileResponse(message.file.open("rb"))
    response["Cache-Control"] = "private, max-age=86400"
    return response
