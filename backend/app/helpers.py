"""
Shared helper functions used by multiple route modules.
Avoids duplication and keeps route files focused on HTTP handling.
"""

import logging
from datetime import datetime
from typing import Optional, List
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import (
    Dataset, IngestionRun, InsightsRun, InsightsItem, AIAuditLog, Job,
)

logger = logging.getLogger(__name__)


# ── UUID parsing ────────────────────────────────────────────────────────

def parse_uuid(value: str, field_name: str = "id") -> UUID:
    """Parse a string into a UUID or raise a 400 HTTPException."""
    try:
        return UUID(str(value))
    except Exception:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}")


# ── Dataset lookup ──────────────────────────────────────────────────────

def get_last_updated(db: Session) -> Optional[str]:
    last_ingestion = db.query(IngestionRun).order_by(IngestionRun.ingested_at.desc()).first()
    return last_ingestion.ingested_at.isoformat() if last_ingestion else None


def get_dataset_or_400(db: Session, dataset_id: Optional[str], plugin_id: str) -> Dataset:
    if not dataset_id:
        raise HTTPException(status_code=400, detail="dataset_id is required")
    ds_uuid = parse_uuid(dataset_id, "dataset_id")
    ds = (
        db.query(Dataset)
        .filter(Dataset.dataset_id == ds_uuid, Dataset.is_deleted == False)  # noqa: E712
        .first()
    )
    if not ds:
        raise HTTPException(status_code=404, detail="Dataset not found")
    # Dynamic datasets can belong to any plugin; only enforce for static
    if getattr(ds, "schema_type", "static") == "static" and ds.plugin_id != plugin_id:
        raise HTTPException(status_code=400, detail="Dataset does not belong to the specified plugin")
    return ds


def dataset_to_meta(ds: Dataset) -> dict:
    meta = {
        "dataset_id": str(ds.dataset_id),
        "plugin_id": ds.plugin_id,
        "plugin": ds.plugin_id,
        "dataset_name": ds.dataset_name,
        "created_at": ds.created_at.isoformat() if ds.created_at else None,
        "last_ingested_at": ds.last_ingested_at.isoformat() if ds.last_ingested_at else None,
        "row_count": ds.row_count,
        "source_filename": ds.source_filename,
        "filename": ds.source_filename,
        "is_deleted": ds.is_deleted,
        "version": ds.version,
        # Dynamic ingestion fields
        "table_name": getattr(ds, "table_name", None),
        "schema_type": getattr(ds, "schema_type", "static"),
        "file_format": getattr(ds, "file_format", None),
        "column_count": getattr(ds, "column_count", None),
    }
    return meta


# ── Plugin management ───────────────────────────────────────────────────

def ensure_active_plugin(plugin_name: Optional[str] = None):
    """Ensures a plugin is active and returns it."""
    from app import nl_to_sql  # deferred to avoid circular import
    if plugin_name:
        if not nl_to_sql.set_active_plugin(plugin_name):
            raise HTTPException(status_code=404, detail=f"Plugin '{plugin_name}' not found")
    elif not nl_to_sql.ACTIVE_PLUGIN:
        raise HTTPException(status_code=400, detail="No active plugin. Set one first.")
    return nl_to_sql.get_active_plugin()


# ── Audit logging ───────────────────────────────────────────────────────

def record_audit_log(
    db: Session,
    *,
    plugin_id: Optional[str],
    dataset_id: Optional[str],
    user_question: Optional[str],
    intent: Optional[str],
    generated_sql: Optional[str],
    sql_valid: Optional[bool],
    execution_ms: Optional[int],
    rows_returned: Optional[int],
    confidence: Optional[str],
    failure_reason: Optional[str],
    model_name: Optional[str],
    prompt_version: str = "v2",
):
    """Persist audit trail; best-effort."""
    try:
        entry = AIAuditLog(
            plugin_id=plugin_id,
            dataset_id=dataset_id,
            user_question=user_question,
            intent=intent,
            generated_sql=generated_sql,
            sql_valid=sql_valid,
            execution_ms=execution_ms,
            rows_returned=rows_returned,
            confidence=confidence,
            failure_reason=failure_reason,
            model_name=model_name,
            prompt_version=prompt_version,
        )
        db.add(entry)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to write audit log: {e}")


# ── Insight helpers ─────────────────────────────────────────────────────

def persist_generated_insights(db: Session, insights: List, plugin: str, dataset_id: Optional[str]):
    from dataclasses import asdict
    run = InsightsRun(plugin=plugin, dataset_id=dataset_id)
    db.add(run)
    db.flush()
    for insight in insights:
        item = InsightsItem(
            run_id=run.run_id,
            insight_id=insight.insight_id,
            severity=insight.severity,
            payload=asdict(insight),
        )
        db.add(item)
    db.commit()
    return run.run_id


def fetch_latest_insights(db: Session, plugin: str, dataset_id: Optional[str], limit: int = 10) -> List[dict]:
    run_query = db.query(InsightsRun).filter(InsightsRun.plugin == plugin)
    if dataset_id:
        run_query = run_query.filter(InsightsRun.dataset_id == dataset_id)
    run = run_query.order_by(InsightsRun.generated_at.desc()).first()
    if not run:
        return []
    items = (
        db.query(InsightsItem)
        .filter(InsightsItem.run_id == run.run_id)
        .order_by(InsightsItem.severity.desc())
        .limit(limit)
        .all()
    )
    return [item.payload for item in items]


def maybe_answer_with_cached_insights(question: str, plugin: str, dataset_id: Optional[str], db: Session, last_updated: Optional[str]):
    q_lower = question.lower()
    if "insight" not in q_lower:
        return None
    insights = fetch_latest_insights(db, plugin, dataset_id, limit=5)
    if not insights:
        return {
            "answer_type": "insights", "answer": [],
            "explanation": "No cached insights available. Run /insights/run to generate them.",
            "data_last_updated": last_updated, "confidence": "low", "plugin": plugin,
        }
    filtered = insights
    if "critical" in q_lower:
        critical_only = [i for i in insights if i.get("severity") == "critical"]
        if critical_only:
            filtered = critical_only
    return {
        "answer_type": "insights", "answer": filtered,
        "explanation": "Served from latest generated insights cache; no recomputation performed.",
        "data_last_updated": last_updated, "confidence": "medium", "plugin": plugin,
    }


# ── Job helpers ─────────────────────────────────────────────────────────

def create_job(db: Session, job_type: str, plugin_id: str, dataset_id: Optional[str], payload: dict) -> UUID:
    job = Job(job_type=job_type, plugin_id=plugin_id, dataset_id=dataset_id, status="QUEUED", payload=payload)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job.job_id


def update_job_status(db: Session, job_id: UUID, status: str, result: Optional[dict] = None, failure: Optional[str] = None, trace: Optional[str] = None, progress: Optional[int] = None):
    job = db.query(Job).filter(Job.job_id == job_id).first()
    if not job:
        return
    now = datetime.utcnow()
    if status == "RUNNING":
        job.started_at = now
    if status in ("SUCCEEDED", "FAILED"):
        job.finished_at = now
    job.status = status
    if result is not None:
        job.result = result
    if failure:
        job.failure_reason = failure
    if trace:
        job.failure_trace = trace[:8000]
    if progress is not None:
        job.progress_pct = progress
    db.add(job)
    db.commit()
