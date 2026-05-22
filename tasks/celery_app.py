from celery import Celery
from celery.schedules import crontab
from config.settings import settings

app = Celery(
    "sales_agents",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "tasks.draft_campaign",
        "tasks.send_approved",
        "tasks.check_replies",
        "tasks.classify_reply",
        "tasks.refresh_voice_examples",
        "tasks.embed_message",
    ],
)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    beat_schedule={
        "send-approved-every-5min": {
            "task": "tasks.send_approved.send_approved_messages",
            "schedule": crontab(minute="*/5"),
        },
        "check-replies-every-15min": {
            "task": "tasks.check_replies.check_all_replies",
            "schedule": crontab(minute="*/15"),
        },
        "refresh-voice-examples-daily": {
            "task": "tasks.refresh_voice_examples.refresh_all_tenants",
            "schedule": crontab(hour=2, minute=0),
        },
    },
)
