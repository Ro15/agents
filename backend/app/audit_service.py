"""
Audit Log Engine — Task 3.3
Immutable append-only log for every query, upload, delete, and schema change.
SOC 2 / GDPR ready.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def log_event(
    db: Session,
    *,
    event_type: str,                        # query | upload | delete | schema_change | export
    plugin_id: Optional[str] = None,
    dataset_id: Optional[str] = None,
    sql_executed: Optional[str] = None,
    rows_returned: Optional[int] = None,
    user_session_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    duration_ms: Optional[int] = None,
    pii_columns_accessed: Optional[list[str]] = None,
    extra: Optional[dict] = None,
) -> None:
    """
    Append a record to the immutable audit log.
    Failures are swallowed (logged as warnings) so they never block the main request.
    """
    try:
        from app.models import AuditLog  # imported here to avoid circular deps at module load
        entry = AuditLog(
            event_type=event_type,
            plugin_id=plugin_id,
            dataset_id=dataset_id,
            sql_executed=sql_executed[:8000] if sql_executed else None,
            rows_returned=rows_returned,
            user_session_id=user_session_id,
            ip_address=ip_address,
            duration_ms=duration_ms,
            pii_columns_accessed=pii_columns_accessed or [],
            extra=extra or {},
        )
        db.add(entry)
        db.commit()
    except Exception as e:
        logger.warning(f"Audit log write failed (non-blocking): {e}")
        try:
            db.rollback()
        except Exception:
            pass


def get_audit_log(
    db: Session,
    plugin_id: Optional[str] = None,
    dataset_id: Optional[str] = None,
    event_type: Optional[str] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """Return audit log entries as dicts (for the /audit-log endpoint)."""
    try:
        from app.models import AuditLog
        q = db.query(AuditLog)
        if plugin_id:
            q = q.filter(AuditLog.plugin_id == plugin_id)
        if dataset_id:
            q = q.filter(AuditLog.dataset_id == dataset_id)
        if event_type:
            q = q.filter(AuditLog.event_type == event_type)
        if start:
            q = q.filter(AuditLog.created_at >= start)
        if end:
            q = q.filter(AuditLog.created_at <= end)
        rows = q.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit).all()
        return [
            {
                "id": str(r.id),
                "event_type": r.event_type,
                "plugin_id": r.plugin_id,
                "dataset_id": r.dataset_id,
                "sql_executed": r.sql_executed,
                "rows_returned": r.rows_returned,
                "user_session_id": r.user_session_id,
                "ip_address": r.ip_address,
                "duration_ms": r.duration_ms,
                "pii_columns_accessed": r.pii_columns_accessed or [],
                "extra": r.extra or {},
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    except Exception as e:
        logger.warning(f"Audit log read failed: {e}")
        return []
