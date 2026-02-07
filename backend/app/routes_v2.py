"""
Routes for new features (v2):
1. Multi-turn conversations
2. Narratives (integrated into /chat via generate_narrative)
3. Data connectors
4. Scheduled reports
5. Custom dashboard builder
6. Query history & favorites
7. Feedback & query correction
8. Rate limiting & LLM cost tracking
9. Data catalog / auto-profiling
"""

import logging
import os
import time
import secrets
import threading
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from uuid import uuid4, UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import text, func
from sqlalchemy.orm import Session

from app.database import engine, SessionLocal
from app.models_v2 import (
    ConversationThread,
    ConversationMessage,
    QueryHistoryEntry,
    QueryFeedback,
    CustomDashboard,
    DashboardWidget,
    ScheduledReport,
    DataConnector,
    ColumnProfile,
    RateLimitLog,
    LLMCostLog,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Dependency ──────────────────────────────────────────────────────────

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════
# 1. MULTI-TURN CONVERSATIONS
# ═══════════════════════════════════════════════════════════════════════

class ConversationCreateRequest(BaseModel):
    plugin_id: str
    dataset_id: Optional[str] = None
    title: Optional[str] = None


@router.post("/conversations")
def create_conversation(req: ConversationCreateRequest, db: Session = Depends(get_db)):
    thread = ConversationThread(
        plugin_id=req.plugin_id,
        dataset_id=req.dataset_id,
        title=req.title or "New conversation",
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)
    return {
        "thread_id": str(thread.thread_id),
        "plugin_id": thread.plugin_id,
        "dataset_id": thread.dataset_id,
        "title": thread.title,
        "created_at": thread.created_at.isoformat() if thread.created_at else None,
    }


@router.get("/conversations")
def list_conversations(
    plugin_id: Optional[str] = Query(None),
    dataset_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    q = db.query(ConversationThread)
    if plugin_id:
        q = q.filter(ConversationThread.plugin_id == plugin_id)
    if dataset_id:
        q = q.filter(ConversationThread.dataset_id == dataset_id)
    threads = q.order_by(ConversationThread.updated_at.desc()).limit(limit).all()
    return [
        {
            "thread_id": str(t.thread_id),
            "plugin_id": t.plugin_id,
            "dataset_id": t.dataset_id,
            "title": t.title,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        }
        for t in threads
    ]


@router.get("/conversations/{thread_id}")
def get_conversation(thread_id: str, db: Session = Depends(get_db)):
    try:
        tid = UUID(str(thread_id))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid thread_id")
    thread = db.query(ConversationThread).filter(ConversationThread.thread_id == tid).first()
    if not thread:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = (
        db.query(ConversationMessage)
        .filter(ConversationMessage.thread_id == tid)
        .order_by(ConversationMessage.created_at.asc())
        .all()
    )
    return {
        "thread_id": str(thread.thread_id),
        "plugin_id": thread.plugin_id,
        "dataset_id": thread.dataset_id,
        "title": thread.title,
        "messages": [
            {
                "message_id": str(m.message_id),
                "role": m.role,
                "content": m.content,
                "sql": m.sql,
                "answer_type": m.answer_type,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ],
    }


@router.delete("/conversations/{thread_id}")
def delete_conversation(thread_id: str, db: Session = Depends(get_db)):
    try:
        tid = UUID(str(thread_id))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid thread_id")
    thread = db.query(ConversationThread).filter(ConversationThread.thread_id == tid).first()
    if not thread:
        raise HTTPException(status_code=404, detail="Conversation not found")
    db.query(ConversationMessage).filter(ConversationMessage.thread_id == tid).delete()
    db.delete(thread)
    db.commit()
    return {"status": "deleted", "thread_id": thread_id}


def save_conversation_message(db: Session, thread_id: UUID, role: str, content: str, sql: str = None, answer_type: str = None):
    """Helper to persist a message and touch the thread's updated_at."""
    msg = ConversationMessage(
        thread_id=thread_id,
        role=role,
        content=content,
        sql=sql,
        answer_type=answer_type,
    )
    db.add(msg)
    thread = db.query(ConversationThread).filter(ConversationThread.thread_id == thread_id).first()
    if thread:
        thread.updated_at = datetime.utcnow()
    db.commit()
    return msg


def get_conversation_history(db: Session, thread_id: UUID, max_turns: int = 10) -> List[Dict[str, str]]:
    """Return the last N messages for LLM context."""
    messages = (
        db.query(ConversationMessage)
        .filter(ConversationMessage.thread_id == thread_id)
        .order_by(ConversationMessage.created_at.desc())
        .limit(max_turns * 2)
        .all()
    )
    messages.reverse()
    return [{"role": m.role, "content": m.content or ""} for m in messages]


# ═══════════════════════════════════════════════════════════════════════
# 6. QUERY HISTORY & FAVORITES
# ═══════════════════════════════════════════════════════════════════════

@router.get("/history")
def list_query_history(
    plugin_id: Optional[str] = Query(None),
    dataset_id: Optional[str] = Query(None),
    favorites_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    q = db.query(QueryHistoryEntry)
    if plugin_id:
        q = q.filter(QueryHistoryEntry.plugin_id == plugin_id)
    if dataset_id:
        q = q.filter(QueryHistoryEntry.dataset_id == dataset_id)
    if favorites_only:
        q = q.filter(QueryHistoryEntry.is_favorite == True)
    total = q.count()
    entries = q.order_by(QueryHistoryEntry.created_at.desc()).offset(offset).limit(limit).all()
    return {
        "total": total,
        "items": [
            {
                "id": str(e.id),
                "plugin_id": e.plugin_id,
                "dataset_id": e.dataset_id,
                "question": e.question,
                "sql": e.sql,
                "answer_type": e.answer_type,
                "answer_summary": e.answer_summary,
                "confidence": e.confidence,
                "is_favorite": e.is_favorite,
                "share_token": e.share_token,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in entries
        ],
    }


@router.post("/history/{entry_id}/favorite")
def toggle_favorite(entry_id: str, db: Session = Depends(get_db)):
    try:
        eid = UUID(str(entry_id))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid entry_id")
    entry = db.query(QueryHistoryEntry).filter(QueryHistoryEntry.id == eid).first()
    if not entry:
        raise HTTPException(status_code=404, detail="History entry not found")
    entry.is_favorite = not entry.is_favorite
    db.commit()
    return {"id": str(entry.id), "is_favorite": entry.is_favorite}


@router.post("/history/{entry_id}/share")
def create_share_link(entry_id: str, db: Session = Depends(get_db)):
    try:
        eid = UUID(str(entry_id))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid entry_id")
    entry = db.query(QueryHistoryEntry).filter(QueryHistoryEntry.id == eid).first()
    if not entry:
        raise HTTPException(status_code=404, detail="History entry not found")
    if not entry.share_token:
        entry.share_token = secrets.token_urlsafe(16)
        db.commit()
    return {"id": str(entry.id), "share_token": entry.share_token}


@router.get("/history/shared/{token}")
def get_shared_query(token: str, db: Session = Depends(get_db)):
    entry = db.query(QueryHistoryEntry).filter(QueryHistoryEntry.share_token == token).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Shared query not found")
    return {
        "id": str(entry.id),
        "plugin_id": entry.plugin_id,
        "dataset_id": entry.dataset_id,
        "question": entry.question,
        "sql": entry.sql,
        "answer_type": entry.answer_type,
        "answer_summary": entry.answer_summary,
        "confidence": entry.confidence,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }


def record_query_history(db: Session, plugin_id: str, dataset_id: Optional[str], question: str, sql: Optional[str], answer_type: Optional[str], answer_summary: Optional[str], confidence: Optional[str]) -> UUID:
    """Helper called from the /chat endpoint to record queries."""
    entry = QueryHistoryEntry(
        plugin_id=plugin_id,
        dataset_id=dataset_id,
        question=question,
        sql=sql,
        answer_type=answer_type,
        answer_summary=answer_summary,
        confidence=confidence,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry.id


# ═══════════════════════════════════════════════════════════════════════
# 7. FEEDBACK & QUERY CORRECTION
# ═══════════════════════════════════════════════════════════════════════

class FeedbackRequest(BaseModel):
    plugin_id: str
    question: str
    original_sql: Optional[str] = None
    corrected_sql: Optional[str] = None
    rating: int  # 1 = thumbs-up, -1 = thumbs-down
    comment: Optional[str] = None
    query_history_id: Optional[str] = None


@router.post("/feedback")
def submit_feedback(req: FeedbackRequest, db: Session = Depends(get_db)):
    if req.rating not in (1, -1):
        raise HTTPException(status_code=400, detail="rating must be 1 or -1")
    fb = QueryFeedback(
        query_history_id=UUID(req.query_history_id) if req.query_history_id else None,
        plugin_id=req.plugin_id,
        question=req.question,
        original_sql=req.original_sql,
        corrected_sql=req.corrected_sql,
        rating=req.rating,
        comment=req.comment,
    )
    db.add(fb)
    db.commit()
    db.refresh(fb)
    return {"id": str(fb.id), "status": "recorded"}


@router.get("/feedback")
def list_feedback(
    plugin_id: Optional[str] = Query(None),
    rating: Optional[int] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    q = db.query(QueryFeedback)
    if plugin_id:
        q = q.filter(QueryFeedback.plugin_id == plugin_id)
    if rating is not None:
        q = q.filter(QueryFeedback.rating == rating)
    entries = q.order_by(QueryFeedback.created_at.desc()).limit(limit).all()
    return [
        {
            "id": str(e.id),
            "plugin_id": e.plugin_id,
            "question": e.question,
            "original_sql": e.original_sql,
            "corrected_sql": e.corrected_sql,
            "rating": e.rating,
            "comment": e.comment,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in entries
    ]


@router.get("/feedback/stats")
def feedback_stats(plugin_id: Optional[str] = Query(None), db: Session = Depends(get_db)):
    q = db.query(QueryFeedback)
    if plugin_id:
        q = q.filter(QueryFeedback.plugin_id == plugin_id)
    total = q.count()
    positive = q.filter(QueryFeedback.rating == 1).count()
    negative = q.filter(QueryFeedback.rating == -1).count()
    corrections = q.filter(QueryFeedback.corrected_sql.isnot(None)).count()
    return {
        "total": total,
        "positive": positive,
        "negative": negative,
        "corrections": corrections,
        "approval_rate": round(positive / total, 2) if total else 0,
    }


# ═══════════════════════════════════════════════════════════════════════
# 5. CUSTOM DASHBOARD BUILDER
# ═══════════════════════════════════════════════════════════════════════

class DashboardCreateRequest(BaseModel):
    title: str
    plugin_id: str
    description: Optional[str] = None


class DashboardUpdateRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    layout: Optional[dict] = None


class WidgetCreateRequest(BaseModel):
    title: str
    widget_type: str = "chart"  # chart | kpi | table
    query_text: Optional[str] = None
    sql: Optional[str] = None
    chart_hint: Optional[str] = None
    config: Optional[dict] = None
    position: Optional[dict] = None  # {x, y, w, h}


class WidgetUpdateRequest(BaseModel):
    title: Optional[str] = None
    widget_type: Optional[str] = None
    query_text: Optional[str] = None
    sql: Optional[str] = None
    chart_hint: Optional[str] = None
    config: Optional[dict] = None
    position: Optional[dict] = None


def _dashboard_to_dict(d: CustomDashboard, widgets: list = None):
    return {
        "dashboard_id": str(d.dashboard_id),
        "title": d.title,
        "plugin_id": d.plugin_id,
        "description": d.description,
        "layout": d.layout,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
        "widgets": widgets or [],
    }


def _widget_to_dict(w: DashboardWidget):
    return {
        "widget_id": str(w.widget_id),
        "dashboard_id": str(w.dashboard_id),
        "title": w.title,
        "widget_type": w.widget_type,
        "query_text": w.query_text,
        "sql": w.sql,
        "chart_hint": w.chart_hint,
        "config": w.config,
        "position": w.position,
        "created_at": w.created_at.isoformat() if w.created_at else None,
    }


@router.post("/dashboards")
def create_dashboard(req: DashboardCreateRequest, db: Session = Depends(get_db)):
    d = CustomDashboard(title=req.title, plugin_id=req.plugin_id, description=req.description)
    db.add(d)
    db.commit()
    db.refresh(d)
    return _dashboard_to_dict(d)


@router.get("/dashboards")
def list_dashboards(plugin_id: Optional[str] = Query(None), db: Session = Depends(get_db)):
    q = db.query(CustomDashboard).filter(CustomDashboard.is_deleted == False)
    if plugin_id:
        q = q.filter(CustomDashboard.plugin_id == plugin_id)
    dashboards = q.order_by(CustomDashboard.updated_at.desc()).all()
    result = []
    for d in dashboards:
        widgets = db.query(DashboardWidget).filter(DashboardWidget.dashboard_id == d.dashboard_id).all()
        result.append(_dashboard_to_dict(d, [_widget_to_dict(w) for w in widgets]))
    return result


@router.get("/dashboards/{dashboard_id}")
def get_dashboard(dashboard_id: str, db: Session = Depends(get_db)):
    try:
        did = UUID(str(dashboard_id))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid dashboard_id")
    d = db.query(CustomDashboard).filter(CustomDashboard.dashboard_id == did, CustomDashboard.is_deleted == False).first()
    if not d:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    widgets = db.query(DashboardWidget).filter(DashboardWidget.dashboard_id == did).all()
    return _dashboard_to_dict(d, [_widget_to_dict(w) for w in widgets])


@router.put("/dashboards/{dashboard_id}")
def update_dashboard(dashboard_id: str, req: DashboardUpdateRequest, db: Session = Depends(get_db)):
    try:
        did = UUID(str(dashboard_id))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid dashboard_id")
    d = db.query(CustomDashboard).filter(CustomDashboard.dashboard_id == did, CustomDashboard.is_deleted == False).first()
    if not d:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    if req.title is not None:
        d.title = req.title
    if req.description is not None:
        d.description = req.description
    if req.layout is not None:
        d.layout = req.layout
    d.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(d)
    widgets = db.query(DashboardWidget).filter(DashboardWidget.dashboard_id == did).all()
    return _dashboard_to_dict(d, [_widget_to_dict(w) for w in widgets])


@router.delete("/dashboards/{dashboard_id}")
def delete_dashboard(dashboard_id: str, db: Session = Depends(get_db)):
    try:
        did = UUID(str(dashboard_id))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid dashboard_id")
    d = db.query(CustomDashboard).filter(CustomDashboard.dashboard_id == did).first()
    if not d:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    d.is_deleted = True
    db.commit()
    return {"status": "deleted", "dashboard_id": dashboard_id}


@router.post("/dashboards/{dashboard_id}/widgets")
def add_widget(dashboard_id: str, req: WidgetCreateRequest, db: Session = Depends(get_db)):
    try:
        did = UUID(str(dashboard_id))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid dashboard_id")
    d = db.query(CustomDashboard).filter(CustomDashboard.dashboard_id == did, CustomDashboard.is_deleted == False).first()
    if not d:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    w = DashboardWidget(
        dashboard_id=did,
        title=req.title,
        widget_type=req.widget_type,
        query_text=req.query_text,
        sql=req.sql,
        chart_hint=req.chart_hint,
        config=req.config,
        position=req.position,
    )
    db.add(w)
    d.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(w)
    return _widget_to_dict(w)


@router.put("/dashboards/{dashboard_id}/widgets/{widget_id}")
def update_widget(dashboard_id: str, widget_id: str, req: WidgetUpdateRequest, db: Session = Depends(get_db)):
    try:
        did = UUID(str(dashboard_id))
        wid = UUID(str(widget_id))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid ID format")
    w = db.query(DashboardWidget).filter(DashboardWidget.widget_id == wid, DashboardWidget.dashboard_id == did).first()
    if not w:
        raise HTTPException(status_code=404, detail="Widget not found")
    if req.title is not None:
        w.title = req.title
    if req.widget_type is not None:
        w.widget_type = req.widget_type
    if req.query_text is not None:
        w.query_text = req.query_text
    if req.sql is not None:
        w.sql = req.sql
    if req.chart_hint is not None:
        w.chart_hint = req.chart_hint
    if req.config is not None:
        w.config = req.config
    if req.position is not None:
        w.position = req.position
    # Touch parent dashboard
    d = db.query(CustomDashboard).filter(CustomDashboard.dashboard_id == did).first()
    if d:
        d.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(w)
    return _widget_to_dict(w)


@router.delete("/dashboards/{dashboard_id}/widgets/{widget_id}")
def delete_widget(dashboard_id: str, widget_id: str, db: Session = Depends(get_db)):
    try:
        did = UUID(str(dashboard_id))
        wid = UUID(str(widget_id))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid ID format")
    w = db.query(DashboardWidget).filter(DashboardWidget.widget_id == wid, DashboardWidget.dashboard_id == did).first()
    if not w:
        raise HTTPException(status_code=404, detail="Widget not found")
    db.delete(w)
    db.commit()
    return {"status": "deleted", "widget_id": widget_id}


# ═══════════════════════════════════════════════════════════════════════
# 4. SCHEDULED REPORTS & ALERTS
# ═══════════════════════════════════════════════════════════════════════

class ScheduleCreateRequest(BaseModel):
    title: str
    plugin_id: str
    dataset_id: Optional[str] = None
    schedule_cron: str = "0 8 * * MON"
    report_type: str = "insights"
    config: Optional[dict] = None
    delivery: Optional[dict] = None  # {method: "email"|"slack"|"webhook", target: "..."}


class ScheduleUpdateRequest(BaseModel):
    title: Optional[str] = None
    schedule_cron: Optional[str] = None
    report_type: Optional[str] = None
    config: Optional[dict] = None
    delivery: Optional[dict] = None
    enabled: Optional[bool] = None


def _schedule_to_dict(s: ScheduledReport):
    return {
        "report_id": str(s.report_id),
        "title": s.title,
        "plugin_id": s.plugin_id,
        "dataset_id": s.dataset_id,
        "schedule_cron": s.schedule_cron,
        "report_type": s.report_type,
        "config": s.config,
        "delivery": s.delivery,
        "enabled": s.enabled,
        "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
        "next_run_at": s.next_run_at.isoformat() if s.next_run_at else None,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


@router.post("/schedules")
def create_schedule(req: ScheduleCreateRequest, db: Session = Depends(get_db)):
    s = ScheduledReport(
        title=req.title,
        plugin_id=req.plugin_id,
        dataset_id=req.dataset_id,
        schedule_cron=req.schedule_cron,
        report_type=req.report_type,
        config=req.config,
        delivery=req.delivery,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return _schedule_to_dict(s)


@router.get("/schedules")
def list_schedules(
    plugin_id: Optional[str] = Query(None),
    enabled: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(ScheduledReport)
    if plugin_id:
        q = q.filter(ScheduledReport.plugin_id == plugin_id)
    if enabled is not None:
        q = q.filter(ScheduledReport.enabled == enabled)
    items = q.order_by(ScheduledReport.created_at.desc()).all()
    return [_schedule_to_dict(s) for s in items]


@router.get("/schedules/{report_id}")
def get_schedule(report_id: str, db: Session = Depends(get_db)):
    try:
        rid = UUID(str(report_id))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid report_id")
    s = db.query(ScheduledReport).filter(ScheduledReport.report_id == rid).first()
    if not s:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return _schedule_to_dict(s)


@router.put("/schedules/{report_id}")
def update_schedule(report_id: str, req: ScheduleUpdateRequest, db: Session = Depends(get_db)):
    try:
        rid = UUID(str(report_id))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid report_id")
    s = db.query(ScheduledReport).filter(ScheduledReport.report_id == rid).first()
    if not s:
        raise HTTPException(status_code=404, detail="Schedule not found")
    if req.title is not None:
        s.title = req.title
    if req.schedule_cron is not None:
        s.schedule_cron = req.schedule_cron
    if req.report_type is not None:
        s.report_type = req.report_type
    if req.config is not None:
        s.config = req.config
    if req.delivery is not None:
        s.delivery = req.delivery
    if req.enabled is not None:
        s.enabled = req.enabled
    db.commit()
    db.refresh(s)
    return _schedule_to_dict(s)


@router.delete("/schedules/{report_id}")
def delete_schedule(report_id: str, db: Session = Depends(get_db)):
    try:
        rid = UUID(str(report_id))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid report_id")
    s = db.query(ScheduledReport).filter(ScheduledReport.report_id == rid).first()
    if not s:
        raise HTTPException(status_code=404, detail="Schedule not found")
    db.delete(s)
    db.commit()
    return {"status": "deleted", "report_id": report_id}


@router.post("/schedules/{report_id}/run-now")
def run_schedule_now(report_id: str, db: Session = Depends(get_db)):
    """Trigger an immediate run of a scheduled report."""
    try:
        rid = UUID(str(report_id))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid report_id")
    s = db.query(ScheduledReport).filter(ScheduledReport.report_id == rid).first()
    if not s:
        raise HTTPException(status_code=404, detail="Schedule not found")
    s.last_run_at = datetime.utcnow()
    db.commit()
    # In production this would trigger actual report generation and delivery
    return {
        "status": "triggered",
        "report_id": report_id,
        "report_type": s.report_type,
        "delivery": s.delivery,
        "run_at": s.last_run_at.isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════════
# 3. DATA CONNECTORS
# ═══════════════════════════════════════════════════════════════════════

SUPPORTED_CONNECTOR_TYPES = {"postgresql", "mysql", "mssql", "bigquery", "snowflake", "excel", "sheets", "api"}


class ConnectorCreateRequest(BaseModel):
    name: str
    connector_type: str
    config: Optional[dict] = None
    plugin_id: Optional[str] = None


class ConnectorUpdateRequest(BaseModel):
    name: Optional[str] = None
    config: Optional[dict] = None
    plugin_id: Optional[str] = None


def _connector_to_dict(c: DataConnector):
    # Redact sensitive fields in config
    safe_config = {}
    if c.config:
        for k, v in c.config.items():
            if any(secret in k.lower() for secret in ("password", "secret", "key", "token")):
                safe_config[k] = "***"
            else:
                safe_config[k] = v
    return {
        "connector_id": str(c.connector_id),
        "name": c.name,
        "connector_type": c.connector_type,
        "config": safe_config,
        "plugin_id": c.plugin_id,
        "status": c.status,
        "last_sync_at": c.last_sync_at.isoformat() if c.last_sync_at else None,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


@router.post("/connectors")
def create_connector(req: ConnectorCreateRequest, db: Session = Depends(get_db)):
    if req.connector_type not in SUPPORTED_CONNECTOR_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported type. Supported: {sorted(SUPPORTED_CONNECTOR_TYPES)}")
    c = DataConnector(
        name=req.name,
        connector_type=req.connector_type,
        config=req.config,
        plugin_id=req.plugin_id,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return _connector_to_dict(c)


@router.get("/connectors")
def list_connectors(plugin_id: Optional[str] = Query(None), db: Session = Depends(get_db)):
    q = db.query(DataConnector)
    if plugin_id:
        q = q.filter(DataConnector.plugin_id == plugin_id)
    connectors = q.order_by(DataConnector.created_at.desc()).all()
    return [_connector_to_dict(c) for c in connectors]


@router.get("/connectors/{connector_id}")
def get_connector(connector_id: str, db: Session = Depends(get_db)):
    try:
        cid = UUID(str(connector_id))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid connector_id")
    c = db.query(DataConnector).filter(DataConnector.connector_id == cid).first()
    if not c:
        raise HTTPException(status_code=404, detail="Connector not found")
    return _connector_to_dict(c)


@router.put("/connectors/{connector_id}")
def update_connector(connector_id: str, req: ConnectorUpdateRequest, db: Session = Depends(get_db)):
    try:
        cid = UUID(str(connector_id))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid connector_id")
    c = db.query(DataConnector).filter(DataConnector.connector_id == cid).first()
    if not c:
        raise HTTPException(status_code=404, detail="Connector not found")
    if req.name is not None:
        c.name = req.name
    if req.config is not None:
        c.config = req.config
    if req.plugin_id is not None:
        c.plugin_id = req.plugin_id
    db.commit()
    db.refresh(c)
    return _connector_to_dict(c)


@router.delete("/connectors/{connector_id}")
def delete_connector(connector_id: str, db: Session = Depends(get_db)):
    try:
        cid = UUID(str(connector_id))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid connector_id")
    c = db.query(DataConnector).filter(DataConnector.connector_id == cid).first()
    if not c:
        raise HTTPException(status_code=404, detail="Connector not found")
    db.delete(c)
    db.commit()
    return {"status": "deleted", "connector_id": connector_id}


@router.post("/connectors/{connector_id}/test")
def test_connector(connector_id: str, db: Session = Depends(get_db)):
    """Test a data source connection."""
    try:
        cid = UUID(str(connector_id))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid connector_id")
    c = db.query(DataConnector).filter(DataConnector.connector_id == cid).first()
    if not c:
        raise HTTPException(status_code=404, detail="Connector not found")

    status = "error"
    message = "Connection test not implemented for this type"

    if c.connector_type == "postgresql":
        try:
            from sqlalchemy import create_engine as _ce
            cfg = c.config or {}
            url = cfg.get("url", "")
            if url:
                test_engine = _ce(url)
                with test_engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                status = "connected"
                message = "Connection successful"
                test_engine.dispose()
        except Exception as e:
            message = str(e)
    elif c.connector_type in ("mysql", "mssql", "bigquery", "snowflake"):
        # Placeholder: real implementation would use the corresponding driver
        status = "configured"
        message = f"{c.connector_type} connection test requires the corresponding driver. Configuration saved."
    elif c.connector_type in ("excel", "sheets"):
        status = "configured"
        message = "File-based connector configured. Upload or provide file URL to sync."
    elif c.connector_type == "api":
        status = "configured"
        message = "API connector configured. Provide endpoint URL in config to test."

    c.status = status
    db.commit()
    return {"connector_id": str(c.connector_id), "status": status, "message": message}


@router.post("/connectors/{connector_id}/sync")
def sync_connector(connector_id: str, db: Session = Depends(get_db)):
    """Trigger data sync from a connector."""
    try:
        cid = UUID(str(connector_id))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid connector_id")
    c = db.query(DataConnector).filter(DataConnector.connector_id == cid).first()
    if not c:
        raise HTTPException(status_code=404, detail="Connector not found")
    c.last_sync_at = datetime.utcnow()
    db.commit()
    return {
        "connector_id": str(c.connector_id),
        "status": "sync_triggered",
        "last_sync_at": c.last_sync_at.isoformat(),
        "message": "Sync initiated. In production this would pull data from the configured source.",
    }


# ═══════════════════════════════════════════════════════════════════════
# 9. DATA CATALOG / AUTO-PROFILING
# ═══════════════════════════════════════════════════════════════════════

@router.post("/catalog/profile/{dataset_id}")
def profile_dataset(dataset_id: str, db: Session = Depends(get_db)):
    """Run auto-profiling on a dataset's columns. Produces stats for the data catalog."""
    try:
        ds_uuid = UUID(str(dataset_id))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid dataset_id")

    # Check the dataset exists
    from app.main import Dataset
    ds = db.query(Dataset).filter(Dataset.dataset_id == ds_uuid, Dataset.is_deleted == False).first()
    if not ds:
        raise HTTPException(status_code=404, detail="Dataset not found")

    # Delete previous profiles for this dataset
    db.query(ColumnProfile).filter(ColumnProfile.dataset_id == ds_uuid).delete()

    # Profile columns from sales_transactions for this dataset
    try:
        col_rows = db.execute(
            text("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_name = 'sales_transactions'
                ORDER BY ordinal_position
            """)
        ).fetchall()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not read schema: {e}")

    profiles = []
    for col_name, data_type in col_rows:
        if col_name in ("id",):
            continue  # skip PK
        try:
            stats = db.execute(
                text(f"""
                    SELECT
                        COUNT(*) FILTER (WHERE "{col_name}" IS NULL) AS null_count,
                        COUNT(DISTINCT "{col_name}") AS distinct_count,
                        MIN("{col_name}"::text) AS min_val,
                        MAX("{col_name}"::text) AS max_val
                    FROM sales_transactions
                    WHERE dataset_id = :dsid
                """),
                {"dsid": ds_uuid},
            ).fetchone()

            # Try to get mean for numeric columns
            mean_val = None
            if data_type in ("numeric", "integer", "bigint", "double precision", "real"):
                mean_row = db.execute(
                    text(f'SELECT AVG("{col_name}") FROM sales_transactions WHERE dataset_id = :dsid'),
                    {"dsid": ds_uuid},
                ).fetchone()
                if mean_row and mean_row[0] is not None:
                    mean_val = float(mean_row[0])

            # Sample values
            sample_row = db.execute(
                text(f'SELECT DISTINCT "{col_name}"::text FROM sales_transactions WHERE dataset_id = :dsid AND "{col_name}" IS NOT NULL LIMIT 5'),
                {"dsid": ds_uuid},
            ).fetchall()
            sample_values = [r[0] for r in sample_row] if sample_row else []

            profile = ColumnProfile(
                dataset_id=ds_uuid,
                column_name=col_name,
                data_type=data_type,
                null_count=int(stats[0]) if stats else None,
                distinct_count=int(stats[1]) if stats else None,
                min_value=str(stats[2]) if stats and stats[2] is not None else None,
                max_value=str(stats[3]) if stats and stats[3] is not None else None,
                mean_value=mean_val,
                sample_values=sample_values,
            )
            db.add(profile)
            profiles.append(profile)
        except Exception as e:
            logger.warning(f"Failed to profile column {col_name}: {e}")
            continue

    db.commit()

    return {
        "dataset_id": dataset_id,
        "columns_profiled": len(profiles),
        "profiles": [
            {
                "column_name": p.column_name,
                "data_type": p.data_type,
                "null_count": p.null_count,
                "distinct_count": p.distinct_count,
                "min_value": p.min_value,
                "max_value": p.max_value,
                "mean_value": float(p.mean_value) if p.mean_value is not None else None,
                "description": p.description,
                "sample_values": p.sample_values,
            }
            for p in profiles
        ],
    }


@router.get("/catalog/{dataset_id}")
def get_catalog(dataset_id: str, db: Session = Depends(get_db)):
    """Get column profiles for a dataset."""
    try:
        ds_uuid = UUID(str(dataset_id))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid dataset_id")
    profiles = db.query(ColumnProfile).filter(ColumnProfile.dataset_id == ds_uuid).order_by(ColumnProfile.column_name).all()
    return {
        "dataset_id": dataset_id,
        "columns": [
            {
                "id": str(p.id),
                "column_name": p.column_name,
                "data_type": p.data_type,
                "null_count": p.null_count,
                "distinct_count": p.distinct_count,
                "min_value": p.min_value,
                "max_value": p.max_value,
                "mean_value": float(p.mean_value) if p.mean_value is not None else None,
                "description": p.description,
                "sample_values": p.sample_values,
                "profiled_at": p.profiled_at.isoformat() if p.profiled_at else None,
            }
            for p in profiles
        ],
    }


@router.put("/catalog/{dataset_id}/columns/{column_name}")
def update_column_description(dataset_id: str, column_name: str, description: str = Query(...), db: Session = Depends(get_db)):
    """Update a column's description in the data catalog."""
    try:
        ds_uuid = UUID(str(dataset_id))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid dataset_id")
    profile = (
        db.query(ColumnProfile)
        .filter(ColumnProfile.dataset_id == ds_uuid, ColumnProfile.column_name == column_name)
        .first()
    )
    if not profile:
        raise HTTPException(status_code=404, detail="Column profile not found. Run /catalog/profile first.")
    profile.description = description
    db.commit()
    return {"dataset_id": dataset_id, "column_name": column_name, "description": description}


# ═══════════════════════════════════════════════════════════════════════
# 8. RATE LIMITING & LLM COST TRACKING
# ═══════════════════════════════════════════════════════════════════════

# In-memory sliding-window rate limiter
_rate_limit_store: Dict[str, list] = defaultdict(list)
_rate_limit_lock = threading.Lock()

RATE_LIMIT_MAX = int(os.getenv("RATE_LIMIT_MAX_REQUESTS", "60"))
RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))


def check_rate_limit(client_ip: str) -> bool:
    """Returns True if request is allowed, False if rate-limited."""
    now = time.time()
    cutoff = now - RATE_LIMIT_WINDOW
    with _rate_limit_lock:
        timestamps = _rate_limit_store[client_ip]
        # Prune old entries
        timestamps[:] = [t for t in timestamps if t > cutoff]
        if len(timestamps) >= RATE_LIMIT_MAX:
            return False
        timestamps.append(now)
    return True


def log_rate_limit(db: Session, client_ip: str, endpoint: str):
    """Best-effort log of rate-limited requests."""
    try:
        entry = RateLimitLog(client_ip=client_ip, endpoint=endpoint)
        db.add(entry)
        db.commit()
    except Exception:
        db.rollback()


def log_llm_cost(db: Session, plugin_id: str, model_name: str, input_tokens: int, output_tokens: int, endpoint: str = "/chat"):
    """Record LLM usage for cost tracking."""
    # Rough cost estimation (per 1K tokens)
    cost_map = {
        "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
        "gpt-4": {"input": 0.03, "output": 0.06},
        "gemini-2.0-flash": {"input": 0.0001, "output": 0.0004},
    }
    rates = cost_map.get(model_name, {"input": 0.0005, "output": 0.0015})
    estimated = (input_tokens / 1000) * rates["input"] + (output_tokens / 1000) * rates["output"]
    try:
        entry = LLMCostLog(
            plugin_id=plugin_id,
            model_name=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost=round(estimated, 6),
            endpoint=endpoint,
        )
        db.add(entry)
        db.commit()
    except Exception:
        db.rollback()


@router.get("/usage/costs")
def get_usage_costs(
    plugin_id: Optional[str] = Query(None),
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    """Return LLM cost summary."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    q = db.query(LLMCostLog).filter(LLMCostLog.created_at >= cutoff)
    if plugin_id:
        q = q.filter(LLMCostLog.plugin_id == plugin_id)
    entries = q.all()
    total_input = sum(e.input_tokens or 0 for e in entries)
    total_output = sum(e.output_tokens or 0 for e in entries)
    total_cost = sum(float(e.estimated_cost or 0) for e in entries)
    by_model: Dict[str, dict] = {}
    for e in entries:
        m = e.model_name or "unknown"
        if m not in by_model:
            by_model[m] = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost": 0.0}
        by_model[m]["calls"] += 1
        by_model[m]["input_tokens"] += e.input_tokens or 0
        by_model[m]["output_tokens"] += e.output_tokens or 0
        by_model[m]["cost"] += float(e.estimated_cost or 0)
    return {
        "period_days": days,
        "total_calls": len(entries),
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_estimated_cost_usd": round(total_cost, 4),
        "by_model": by_model,
    }


@router.get("/usage/limits")
def get_rate_limit_status(request: Request):
    """Return current rate limit status for the caller."""
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    cutoff = now - RATE_LIMIT_WINDOW
    with _rate_limit_lock:
        timestamps = _rate_limit_store.get(client_ip, [])
        recent = [t for t in timestamps if t > cutoff]
    return {
        "client_ip": client_ip,
        "requests_in_window": len(recent),
        "max_requests": RATE_LIMIT_MAX,
        "window_seconds": RATE_LIMIT_WINDOW,
        "remaining": max(0, RATE_LIMIT_MAX - len(recent)),
    }
