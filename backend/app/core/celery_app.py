from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "jezseem_erp",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

# Task modules are registered here as they're built, e.g.:
# celery_app.autodiscover_tasks(["app.integrations"])
