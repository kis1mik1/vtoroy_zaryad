from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Count, Prefetch, Q
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.accounts.decorators import verified_email_required
from apps.catalog.models import Category
from apps.catalog.selectors import brands_for, get_category_tree, model_with_specs, models_for
from apps.core.decorators import ratelimit
from apps.core.ratelimit import Rate, hit

from .. import services
from ..forms import OTHER_MODEL, AdForm, AttributesForm, ConditionForm
from ..market import price_hint
from ..models import MAX_PHOTOS, Ad, AdPhoto, AdStatus, Condition
from ..photos import resolve_photos, upload_photo

CREATE_RATE = Rate(limit=20, period=24 * 60 * 60)
PHOTO_RATE = Rate(limit=100, period=60 * 60)

STATUS_TABS = (
    (AdStatus.ACTIVE, "Активные"),
    (AdStatus.PENDING, "На проверке"),
    (AdStatus.REJECTED, "Отклонённые"),
    (AdStatus.SOLD, "Проданные"),
    (AdStatus.ARCHIVED, "Архив"),
)


def _leaf(value):
    if not value or not str(value).isdigit():
        return None
    return Category.objects.filter(pk=value, is_active=True, children__isnull=True).first()


def _model(value, category):
    if category is None or not value or not str(value).isdigit():
        return None
    model = model_with_specs(value)
    return model if model and model.category_id == category.pk else None


class AdFormState:
    def __init__(self, request, ad=None):
        source = request.POST if request.method == "POST" else request.GET
        bound = request.method == "POST"
        self.ad = ad
        self.category = _leaf(source.get("category")) or (ad.category if ad and not bound else None)
        raw_model = source.get("device_model", "")
        if not raw_model and ad and not bound:
            raw_model = str(ad.device_model_id or OTHER_MODEL)
        self.model_value = raw_model
        self.device_model = _model(raw_model, self.category)
        brand = source.get("brand", "")
        if not brand and ad and not bound:
            brand = str(ad.brand_id or "")
        self.brand_value = str(self.device_model.brand_id) if self.device_model else brand
        self.condition = source.get("condition") or (ad.condition if ad else "")

        initial = {}
        if ad is None:
            initial = {"city": request.city or request.user.city, "condition": Condition.USED}
        self.ad_form = AdForm(request.POST if bound else None, instance=ad, initial=initial)

        attr_initial = AttributesForm.initial_from_ad(ad) if ad and not bound else {}
        attr_data = request.POST if bound else None
        self.attributes_form = AttributesForm(
            self.category, self.device_model, attr_data, initial=attr_initial or source
        )

        report = getattr(ad, "condition_report", None) if ad else None
        self.condition_form = ConditionForm(
            request.POST if bound else None,
            instance=report,
            condition=self.condition,
            category=self.category,
        )

        self.photos = []
        self.photo_error = ""
        if bound:
            try:
                self.photos = resolve_photos(request.user, request.POST.getlist("photos"), ad)
            except ValidationError as exc:
                self.photo_error = exc.messages[0]
            if not self.photos and not self.photo_error:
                self.photo_error = "Добавьте хотя бы одно фото."
        elif ad:
            self.photos = list(ad.photos.all())

    def is_valid(self) -> bool:
        forms_valid = [
            self.ad_form.is_valid(),
            self.attributes_form.is_valid(),
            self.condition_form.is_valid(),
        ]
        return all(forms_valid) and not self.photo_error

    def draft(self) -> services.AdDraft:
        return services.AdDraft(
            fields=self.ad_form.ad_fields(),
            attributes=self.attributes_form.values(),
            condition=self.condition_form.report_data(),
            photos=self.photos,
        )

    def context(self) -> dict:
        brands = list(brands_for(self.category)) if self.category else []
        models = (
            models_for(self.category, self.brand_value)
            if self.category and self.brand_value.isdigit()
            else []
        )
        return {
            "state": self,
            "form": self.ad_form,
            "attributes_form": self.attributes_form,
            "condition_form": self.condition_form,
            "tree": get_category_tree(),
            "brands": brands,
            "models": models,
            "other_model": OTHER_MODEL,
            "max_photos": MAX_PHOTOS,
            "price_hint": price_hint(
                self.device_model, self.condition, self.attributes_form.price_key()
            ),
        }


def _after_review_request(request, ad: Ad):
    ad.refresh_from_db()
    if ad.status == AdStatus.ACTIVE:
        messages.success(request, "Объявление проверено и опубликовано.")
    elif ad.status == AdStatus.REJECTED:
        messages.error(request, f"Объявление не прошло проверку. {ad.rejection_reason}")
    elif ad.is_checking:
        messages.success(
            request, "Объявление отправлено на проверку. Обычно она занимает несколько секунд."
        )
    else:
        messages.success(
            request,
            "Объявление отправлено модератору. Он посмотрит его в течение рабочего дня.",
        )
    return redirect(f"{reverse('ads:my_ads')}?status={ad.status}")


@verified_email_required
@require_http_methods(["GET", "POST"])
def ad_create(request):
    state = AdFormState(request)
    if request.method == "POST" and state.is_valid():
        hit("ad-create", f"user:{request.user.pk}", CREATE_RATE)
        ad = services.create_ad(request.user, state.draft())
        return _after_review_request(request, ad)
    context = state.context()
    context.update(
        title="Новое объявление",
        breadcrumbs=[("Новое объявление", None)],
        submit_label="Отправить на проверку",
    )
    return render(
        request, "ads/ad_form.html", context, status=400 if request.method == "POST" else 200
    )


@verified_email_required
@require_http_methods(["GET", "POST"])
def ad_edit(request, pk):
    ad = get_object_or_404(
        Ad.objects.alive().select_related("category", "device_model", "brand", "condition_report"),
        pk=pk,
        seller=request.user,
    )
    if not ad.is_editable:
        messages.error(request, "Проданное объявление нельзя изменить.")
        return redirect(f"{reverse('ads:my_ads')}?status={ad.status}")
    state = AdFormState(request, ad)
    if request.method == "POST" and state.is_valid():
        if services.update_ad(ad, state.draft()):
            return _after_review_request(request, ad)
        messages.success(request, "Изменения сохранены.")
        ad.refresh_from_db()
        return redirect(f"{reverse('ads:my_ads')}?status={ad.status}")
    context = state.context()
    context.update(
        title="Редактирование объявления",
        breadcrumbs=[("Мои объявления", reverse("ads:my_ads")), ("Редактирование", None)],
        submit_label="Сохранить изменения",
    )
    return render(
        request, "ads/ad_form.html", context, status=400 if request.method == "POST" else 200
    )


@login_required
@require_GET
def ad_form_section(request):
    ad = None
    if request.GET.get("ad", "").isdigit():
        ad = Ad.objects.alive().filter(pk=request.GET["ad"], seller=request.user).first()
    state = AdFormState(request, ad)
    context = state.context()
    context["include_condition"] = request.GET.get("part") == "category"
    return render(request, "ads/partials/model_section.html", context)


@verified_email_required
@require_POST
@ratelimit("ad-photo", PHOTO_RATE, key="user")
def photo_upload(request):
    uploaded = request.FILES.get("photo")
    if uploaded is None:
        return HttpResponseBadRequest("Файл не получен.")
    try:
        photo = upload_photo(request.user, uploaded)
    except ValidationError as exc:
        return HttpResponseBadRequest(exc.messages[0])
    return render(request, "ads/partials/photo_tile.html", {"photo": photo})


def _my_ads_queryset(user):
    return (
        Ad.objects.alive()
        .filter(seller=user)
        .select_related("city", "category")
        .prefetch_related(Prefetch("photos", queryset=AdPhoto.objects.order_by("position", "pk")))
    )


@login_required
@require_GET
def my_ad_row(request, pk):
    ad = get_object_or_404(_my_ads_queryset(request.user), pk=pk)
    return render(request, "ads/partials/my_ad_row.html", {"ad": ad})


@login_required
@require_GET
def my_ads(request):
    status = request.GET.get("status", AdStatus.ACTIVE)
    if status not in AdStatus.values:
        status = AdStatus.ACTIVE
    base = Ad.objects.alive().filter(seller=request.user)
    counts = base.aggregate(
        **{value: Count("pk", filter=Q(status=value)) for value, _ in STATUS_TABS}
    )
    ads = _my_ads_queryset(request.user).filter(status=status).order_by("-status_changed_at")
    return render(
        request,
        "ads/my_ads.html",
        {
            "ads": ads,
            "status": status,
            "tabs": [(value, label, counts[value]) for value, label in STATUS_TABS],
            "breadcrumbs": [("Мои объявления", None)],
        },
    )


@login_required
@require_POST
def ad_status(request, pk, action):
    ad = get_object_or_404(Ad.objects.alive(), pk=pk, seller=request.user)
    transition, message = services.TRANSITIONS.get(action, (None, ""))
    if transition is None:
        return HttpResponseBadRequest("Неизвестное действие.")
    try:
        transition(ad)
    except services.TransitionError as exc:
        messages.error(request, str(exc))
    else:
        ad.refresh_from_db()
        if action == "restore" and ad.status != AdStatus.ACTIVE:
            return _after_review_request(request, ad)
        messages.success(request, message)
    ad.refresh_from_db()
    target = AdStatus.ACTIVE if ad.is_deleted else ad.status
    return redirect(f"{reverse('ads:my_ads')}?status={target}")
