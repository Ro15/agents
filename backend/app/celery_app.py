"""
Celery application — Task 5.2
Async heavy operations: ingestion, insight generation, RCA, forecasting.

Queues:
  default — lightweight tasks (cache invalidation, audit events)
  heavy   — CPU/IO-intensive tasks (ingestion, forecasting, RCA, insight generation)
"""
from __future__ import annotations

import logging
import os

from celery import Celery

logger = logging.getLogger(__name__)

BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1")
RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")

celery_app = Celery(
    "agent_x",
    broker=BROKER_URL,
    backend=RESULT_BACKEND,
    include=["app.celery_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_routes={
        "app.celery_tasks.run_ingestion_task": {"queue": "heavy"},
        "app.celery_tasks.run_insights_task": {"queue": "heavy"},
        "app.celery_tasks.run_forecast_task": {"queue": "heavy"},
        "app.celery_tasks.run_rca_task": {"queue": "heavy"},
        "app.celery_tasks.invalidate_cache_task": {"queue": "default"},
    },
    task_soft_time_limit=120,   # 2 min soft kill
    task_time_limit=180,        # 3 min hard kill
    worker_prefetch_multiplier=1,
    task_acks_late=True,
)
