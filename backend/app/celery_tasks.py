"""
Celery task definitions — heavy async operations.
Import celery_app from celery_app.py; never import this from the FastAPI
request path (avoids circular imports and blocking the event loop).
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from app.celery_app import celery_app

logger = logging.getLogger(__name__)


def _get_db():
    from app.database import SessionLocal
    return SessionLocal()


def _get_engine():
    from app.database import engine
    return engine


# ── Insight generation ────────────────────────────────────────────────────────


@celery_app.task(name="app.celery_tasks.run_insights_task", bind=True, max_retries=2)
def run_insights_task(self, plugin_id: str, dataset_id: str):
    """Generate insights for a dataset in the background."""
    try:
        from app.insight_engine import InsightEngine
        from app import nl_to_sql
        from app.helpers import persist_generated_insights
        from app.database import SessionLocal

        plugin = None
        if nl_to_sql.PLUGIN_MANAGER:
            plugin = nl_to_sql.PLUGIN_MANAGER.get_plugin(plugin_id)
        if plugin is None:
            logger.warning(f"[celery] Plugin '{plugin_id}' not found for insights task")
            return {"status": "skipped", "reason": "plugin_not_found"}

        engine_inst = InsightEngine(plugin)
        insights = engine_inst.generate_insights()

        db = SessionLocal()
        try:
            persist_generated_insights(db, plugin_id, dataset_id, insights)
            db.commit()
        finally:
            db.close()

        logger.info(f"[celery] Insights generated for {plugin_id}/{dataset_id}: {len(insights)} items")
        return {"status": "ok", "count": len(insights)}
    except Exception as exc:
        logger.error(f"[celery] run_insights_task failed: {exc}")
        raise self.retry(exc=exc, countdown=30)


# ── Forecast ──────────────────────────────────────────────────────────────────


@celery_app.task(name="app.celery_tasks.run_forecast_task", bind=True, max_retries=1)
def run_forecast_task(self, dataset_id: str, date_column: str, value_column: str, horizon: int = 30):
    """Run forecasting and store results (future: write to a forecast_cache table)."""
    try:
        from sqlalchemy import text
        from app.forecast_engine import run_forecast
        from app.models import Dataset

        db = _get_db()
        engine = _get_engine()
        try:
            ds = db.query(Dataset).filter(Dataset.dataset_id == dataset_id).first()
            if not ds or not ds.table_name:
                return {"status": "skipped", "reason": "dataset_not_found"}

            with engine.connect() as conn:
                rows = conn.execute(
                    text(
                        f'SELECT "{date_column}", "{value_column}" FROM "{ds.table_name}" '
                        f'WHERE "{date_column}" IS NOT NULL AND "{value_column}" IS NOT NULL '
                        f'ORDER BY "{date_column}" ASC LIMIT 2000'
                    )
                ).fetchall()

            if len(rows) < 7:
                return {"status": "skipped", "reason": "insufficient_data"}

            dates = [str(r[0]) for r in rows]
            values = [float(r[1]) for r in rows]
            result = run_forecast(dates, values, horizon=horizon)
            if result is None:
                return {"status": "skipped", "reason": "forecast_failed"}

            logger.info(f"[celery] Forecast for {dataset_id} — method={result.method} r²={result.r_squared:.3f}")
            return {"status": "ok", "method": result.method, "r_squared": result.r_squared}
        finally:
            db.close()
    except Exception as exc:
        logger.error(f"[celery] run_forecast_task failed: {exc}")
        raise self.retry(exc=exc, countdown=15)


# ── RCA ───────────────────────────────────────────────────────────────────────


@celery_app.task(name="app.celery_tasks.run_rca_task", bind=True, max_retries=1)
def run_rca_task(self, dataset_id: str, metric_column: str, date_column: str, period_days: int = 7):
    """Run root cause analysis and log results."""
    try:
        from app.rca_engine import run_rca
        from app.models import Dataset

        db = _get_db()
        engine = _get_engine()
        try:
            ds = db.query(Dataset).filter(Dataset.dataset_id == dataset_id).first()
            if not ds or not ds.table_name:
                return {"status": "skipped", "reason": "dataset_not_found"}

            with engine.connect() as conn:
                report = run_rca(ds.table_name, metric_column, date_column, conn, period_days)

            if report is None:
                return {"status": "no_change_detected"}

            logger.info(f"[celery] RCA for {dataset_id}: {len(report.top_contributors)} contributors found")
            return {
                "status": "ok",
                "total_delta": report.total_delta,
                "top_contributor": report.top_contributors[0].dimension if report.top_contributors else None,
            }
        finally:
            db.close()
    except Exception as exc:
        logger.error(f"[celery] run_rca_task failed: {exc}")
        raise self.retry(exc=exc, countdown=15)


# ── Cache invalidation ────────────────────────────────────────────────────────


@celery_app.task(name="app.celery_tasks.invalidate_cache_task")
def invalidate_cache_task(plugin_id: str):
    """Invalidate all result cache entries for a plugin."""
    try:
        from app.result_cache import cache_invalidate_plugin
        deleted = cache_invalidate_plugin(plugin_id)
        logger.info(f"[celery] Cache invalidated for plugin '{plugin_id}': {deleted} keys deleted")
        return {"status": "ok", "deleted": deleted}
    except Exception as exc:
        logger.warning(f"[celery] Cache invalidation failed for '{plugin_id}': {exc}")
        return {"status": "error", "reason": str(exc)}
