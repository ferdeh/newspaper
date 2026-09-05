from celery import Celery
from celery.schedules import crontab

from app.config import settings

celery_app = Celery("fuel_intelligence", broker=settings.redis_url, backend=settings.redis_url, include=["app.workers.tasks"])
celery_app.conf.update(
    timezone=settings.app_timezone,
    enable_utc=True,
    task_acks_late=True,
    task_track_started=True,
    task_reject_on_worker_lost=True,
    broker_connection_retry_on_startup=True,
    result_expires=3600,
    task_routes={
        "fuel.news.collect": {"queue": "news"},
        "fuel.tiktok.discover": {"queue": "tiktok"},
        "fuel.tiktok.search": {"queue": "tiktok"},
        "fuel.tiktok.collect-for-refresh": {"queue": "tiktok"},
        "fuel.signal.process": {"queue": "nlp"},
        "fuel.geo.enrich": {"queue": "geo"},
        "fuel.tbbm.discover": {"queue": "tbbm"},
        "fuel.incident.recalculate": {"queue": "incident"},
        "fuel.analytics.refresh": {"queue": "analytics"},
        "fuel.intelligence.refresh": {"queue": "analytics"},
        "fuel.intelligence.recalculate": {"queue": "incident"},
        "fuel.intelligence.finalize": {"queue": "analytics"},
        "fuel.alerts.evaluate": {"queue": "alerts"},
        "fuel.notifications.dispatch": {"queue": "notifications"},
        "fuel.whatsapp.dispatch": {"queue": "whatsapp"},
        "fuel.whatsapp.digest": {"queue": "whatsapp"},
    },
)

celery_app.conf.beat_schedule = {
    "priority-news": {"task": "fuel.news.collect", "schedule": settings.news_priority_minutes * 60, "args": [1]},
    "general-news": {"task": "fuel.news.collect", "schedule": settings.news_general_minutes * 60, "args": [5]},
    "tiktok-discovery-due-check": {"task": "fuel.tiktok.discover", "schedule": settings.tiktok_due_check_seconds},
    "geography-enrichment": {"task": "fuel.geo.enrich", "schedule": settings.geo_enrichment_minutes * 60},
    "incident-recalculation": {"task": "fuel.incident.recalculate", "schedule": settings.incident_recalc_minutes * 60},
    "analytics-refresh": {"task": "fuel.analytics.refresh", "schedule": settings.analytics_refresh_minutes * 60},
    "alert-evaluation": {"task": "fuel.alerts.evaluate", "schedule": settings.risk_recalc_minutes * 60},
    "whatsapp-delivery": {"task": "fuel.whatsapp.dispatch", "schedule": 60},
    "notification-delivery": {"task": "fuel.notifications.dispatch", "schedule": settings.notification_dispatch_seconds},
    "daily-digest": {"task": "fuel.whatsapp.digest", "schedule": crontab(hour=settings.daily_digest_hour, minute=0)},
}

for service, queue in {
    "news-worker": "news", "tiktok-worker": "tiktok", "nlp-worker": "nlp", "geo-worker": "geo",
    "incident-worker": "incident", "analytics-worker": "analytics", "alert-worker": "alerts",
    "notification-worker": "notifications", "whatsapp-worker": "whatsapp",
}.items():
    celery_app.conf.beat_schedule[f"heartbeat-{service}"] = {
        "task": "fuel.system.heartbeat", "schedule": 30, "args": [service], "options": {"queue": queue}
    }
