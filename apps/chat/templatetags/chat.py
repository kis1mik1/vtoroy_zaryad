from django import template

register = template.Library()


@register.filter
def interlocutor(conversation, user):
    return conversation.other(user)


@register.filter
def duration(seconds) -> str:
    seconds = int(seconds or 0)
    return f"{seconds // 60}:{seconds % 60:02d}"
