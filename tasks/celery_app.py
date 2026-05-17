from celery import Celery
from celery.schedules import crontab
from config.settings import settings

app = Celery(
    "sales_agents",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["tasks.scheduled_tasks"],
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
        "discovery-every-6h": {
            "task": "tasks.scheduled_tasks.discovery_task",
            "schedule": crontab(minute=0, hour="*/6"),
        },
        "qualification-every-2h": {
            "task": "tasks.scheduled_tasks.qualification_task",
            "schedule": crontab(minute=30, hour="*/2"),
        },
        "outreach-every-1h": {
            "task": "tasks.scheduled_tasks.outreach_task",
            "schedule": crontab(minute=15, hour="*"),
        },
        "followup-every-30min": {
            "task": "tasks.scheduled_tasks.followup_task",
            "schedule": crontab(minute="*/30"),
        },
        "conversion-check-every-15min": {
            "task": "tasks.scheduled_tasks.conversion_check_task",
            "schedule": crontab(minute="*/15"),
        },
        "daily-summary-9am": {
            "task": "tasks.scheduled_tasks.daily_summary_task",
            "schedule": crontab(hour=9, minute=0),
        },
    },
)
