from django import template

from apps.ads.selectors import market_label

register = template.Library()


@register.filter
def market(ad):
    return market_label(ad)


@register.filter
def main_photo(ad):
    photos = getattr(ad, "ordered_photos", None)
    if photos is None:
        photos = list(ad.photos.all())
    return photos[0] if photos else None


@register.filter
def field_named(form, name):
    return form[name]
