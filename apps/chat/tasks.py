from celery import shared_task

from . import services


@shared_task(soft_time_limit=150, time_limit=180)
def transcode_voice(message_id: int) -> bool:
    return services.transcode(message_id)


@shared_task
def email_unread_messages() -> int:
    return services.email_unread_messages()
