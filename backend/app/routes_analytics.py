"""
Analytics & Observability routes — Task 1.1, 2.1-2.4, 3.3, 4.3, 6.1, 6.2

Endpoints:
  GET  /health              — enhanced health + circuit breaker status
  GET  /metrics             — Prometheus text format
  GET  /metrics/snapshot    — JSON metrics snapshot
  GET  /audit-log           — immutable audit log query
  GET  /datasets/federation-hints — cross-dataset join hints
  DELETE /cache/{plugin_id} — invalidate result cache for a plugin
  GET  /chat/stream         — SSE streaming chat (Task 1.1)
  POST /agent/generate-report — autonomous report builder (Task 4.3)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime
from typing import Optional, AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse, PlainTextResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import SessionLocal, engine
from app import telemetry
from app.audit_service import get_audit_log
from app.circuit_breaker import all_breaker_statuses
from app.federation_service import get_federation_hints, get_federation_schema_context
from app.result_cache import cache_invalidate_plugin, cache_stats
from app.forecast_engine import run_forecast, is_forecast_question, detect_horizon
from app.rca_engine import run_rca
from app.cohort_engine import detect_cohort_intent, build_cohort_sql, auto_column_map
from app.models import Dataset, ColumnProfile

logger = logging.getLogger(__name__)

router = APIRouter(tags=["analytics"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Health ──────────────────────────────────────────────────────────────────


@router.get("/health")
def health_check(db: Session = Depends(get_db)):
    """Enhanced health endpoint with circuit breaker status."""
    db_ok = False
    try:
        from sqlalchemy import text
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    return {
        "status": "ok" if db_ok else "degraded",
        "db": "ok" if db_ok else "error",
        "circuit_breakers": all_breaker_statuses(),
        "telemetry": telemetry.metrics_snapshot(),
        "timestamp": datetime.utcnow().isoformat(),
    }


# ── Metrics ──────────────────────────────────────────────────────────────────


@router.get("/metrics", response_class=PlainTextResponse)
def prometheus_metrics():
    """Export Prometheus-format metrics."""
    return telemetry.prometheus_output()


@router.get("/metrics/snapshot")
def metrics_snapshot():
    """JSON snapshot of all in-process counters and histograms."""
    return telemetry.metrics_snapshot()


# ── Audit Log ────────────────────────────────────────────────────────────────


@router.get("/audit-log")
def query_audit_log(
    plugin_id: Optional[str] = Query(None),
    dataset_id: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    start: Optional[str] = Query(None, description="ISO datetime (UTC)"),
    end: Optional[str] = Query(None, description="ISO datetime (UTC)"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Query the immutable audit log. All parameters are optional filters."""
    start_dt = datetime.fromisoformat(start) if start else None
    end_dt = datetime.fromisoformat(end) if end else None
    events = get_audit_log(
        db,
        plugin_id=plugin_id,
        dataset_id=dataset_id,
        event_type=event_type,
        start=start_dt,
        end=end_dt,
        limit=limit,
        offset=offset,
    )
    return {"events": events, "count": len(events), "offset": offset}


# ── Federation ────────────────────────────────────────────────────────────────


@router.get("/datasets/federation-hints")
def federation_hints(
    plugin_id: str = Query(..., description="Plugin whose datasets to scan"),
    db: Session = Depends(get_db),
):
    """Discover join candidates across datasets that belong to the same plugin."""
    hints = get_federation_hints(plugin_id, db)
    return {
        "plugin_id": plugin_id,
        "hints": [
            {
                "left_table": h.left_table,
                "left_column": h.left_column,
                "right_table": h.right_table,
                "right_column": h.right_column,
                "overlap_score": round(h.overlap_score, 3),
                "example_values": h.example_values,
            }
            for h in hints
        ],
        "schema_context": get_federation_schema_context(hints),
    }


# ── Cache management ──────────────────────────────────────────────────────────


@router.delete("/cache/{plugin_id}")
def invalidate_cache(plugin_id: str):
    """Invalidate all cached results for a plugin."""
    deleted = cache_invalidate_plugin(plugin_id)
    return {"plugin_id": plugin_id, "keys_deleted": deleted, "status": "ok"}


@router.get("/cache/stats")
def get_cache_stats():
    """Return Redis cache statistics."""
    return cache_stats()


# ── Forecasting endpoint ──────────────────────────────────────────────────────


class ForecastRequest(BaseModel):
    dataset_id: str
    date_column: str
    value_column: str
    horizon: int = 30


@router.post("/analytics/forecast")
def compute_forecast(req: ForecastRequest, db: Session = Depends(get_db)):
    """Run time-series forecast on a dataset column."""
    from sqlalchemy import text as sa_text

    ds = db.query(Dataset).filter(Dataset.dataset_id == req.dataset_id).first()
    if not ds or not ds.table_name:
        raise HTTPException(status_code=404, detail="Dataset not found")

    try:
        with engine.connect() as conn:
            rows = conn.execute(
                sa_text(
                    f'SELECT "{req.date_column}", "{req.value_column}" '
                    f'FROM "{ds.table_name}" '
                    f'WHERE "{req.date_column}" IS NOT NULL AND "{req.value_column}" IS NOT NULL '
                    f'ORDER BY "{req.date_column}" ASC LIMIT 2000'
                )
            ).fetchall()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Query failed: {e}")

    if len(rows) < 7:
        raise HTTPException(status_code=400, detail="Not enough data for forecasting (need at least 7 points)")

    dates = [str(r[0]) for r in rows]
    values = [float(r[1]) for r in rows]
    result = run_forecast(dates, values, horizon=req.horizon)
    if result is None:
        raise HTTPException(status_code=400, detail="Forecasting failed — check data quality")

    return {
        "method": result.method,
        "horizon": result.horizon,
        "r_squared": result.r_squared,
        "historical": [{"date": p.date, "value": p.value} for p in result.historical],
        "predictions": [
            {"date": p.date, "value": p.value, "lower": p.lower, "upper": p.upper}
            for p in result.predictions
        ],
        "message": result.message,
    }


# ── RCA endpoint ──────────────────────────────────────────────────────────────


class RCARequest(BaseModel):
    dataset_id: str
    metric_column: str
    date_column: str
    period_days: int = 7


@router.post("/analytics/rca")
def compute_rca(req: RCARequest, db: Session = Depends(get_db)):
    """Run root cause analysis for a metric column."""
    ds = db.query(Dataset).filter(Dataset.dataset_id == req.dataset_id).first()
    if not ds or not ds.table_name:
        raise HTTPException(status_code=404, detail="Dataset not found")

    try:
        with engine.connect() as conn:
            report = run_rca(ds.table_name, req.metric_column, req.date_column, conn, req.period_days)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"RCA failed: {e}")

    if report is None:
        return {"message": "No significant change detected — RCA not triggered"}

    return {
        "metric": report.metric,
        "table": report.table,
        "total_delta": report.total_delta,
        "top_contributors": [
            {
                "dimension": c.dimension,
                "value": c.value,
                "current": c.current,
                "previous": c.previous,
                "delta_pct": round(c.delta_pct, 2),
                "contribution_pct": round(c.contribution_pct, 2),
            }
            for c in report.top_contributors
        ],
        "explanation": report.explanation,
        "follow_up_questions": report.follow_up_questions,
    }


# ── Cohort endpoint ───────────────────────────────────────────────────────────


class CohortRequest(BaseModel):
    dataset_id: str
    intent: str  # 'retention' | 'funnel' | 'ltv' | 'rfm'
    column_map: Optional[dict] = None


@router.post("/analytics/cohort")
def compute_cohort(req: CohortRequest, db: Session = Depends(get_db)):
    """Generate and execute cohort analysis SQL."""
    from sqlalchemy import text as sa_text

    ds = db.query(Dataset).filter(Dataset.dataset_id == req.dataset_id).first()
    if not ds or not ds.table_name:
        raise HTTPException(status_code=404, detail="Dataset not found")

    col_profiles = db.query(ColumnProfile).filter(ColumnProfile.dataset_id == req.dataset_id).all()
    column_map = req.column_map or auto_column_map(ds.table_name, col_profiles)

    sql = build_cohort_sql(req.intent, column_map)
    if not sql:
        raise HTTPException(status_code=400, detail=f"Cannot build cohort SQL for intent '{req.intent}' — insufficient column mapping")

    try:
        with engine.connect() as conn:
            rows = conn.execute(sa_text(sql)).fetchall()
        result = [dict(r._mapping) for r in rows]
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cohort query failed: {e}")

    return {"intent": req.intent, "sql": sql, "rows": result, "row_count": len(result)}


# ── SSE Streaming Chat ────────────────────────────────────────────────────────


async def _stream_chat_response(question: str, plugin_id: str, dataset_id: Optional[str]) -> AsyncGenerator[str, None]:
    """
    Generator that streams chunks of the chat response as SSE events.
    Reuses the existing LLM service for SQL generation + narrative.
    """
    from app.llm_service import LLMConfig, generate_sql_with_llm, generate_narrative
    from app import nl_to_sql

    def _sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data)}\n\n"

    yield _sse("status", {"message": "Processing your question…"})
    await asyncio.sleep(0)

    try:
        plugin = nl_to_sql.PLUGIN_MANAGER.get_plugin(plugin_id) if nl_to_sql.PLUGIN_MANAGER else None
        if not plugin:
            plugin = nl_to_sql.get_active_plugin()
        if not plugin:
            yield _sse("error", {"message": f"Plugin '{plugin_id}' not found"})
            return

        cfg = LLMConfig()
        if not cfg.available:
            yield _sse("error", {"message": "LLM service unavailable"})
            return

        yield _sse("status", {"message": "Generating SQL…"})
        await asyncio.sleep(0)

        from app.llm_service import SchemaContext as SC
        ctx = SC(
            plugin.schema,
            plugin.get_allowed_tables(),
            plugin.get_allowed_columns(),
            plugin_name=plugin.plugin_name,
        )

        llm_resp = generate_sql_with_llm(question, ctx, cfg)
        if llm_resp is None:
            yield _sse("error", {"message": "SQL generation failed"})
            return

        yield _sse("sql", {"sql": llm_resp.sql, "confidence": llm_resp.confidence if hasattr(llm_resp, "confidence") else "medium"})
        await asyncio.sleep(0)

        yield _sse("status", {"message": "Executing query…"})
        await asyncio.sleep(0)

        from sqlalchemy import text as sa_text
        rows = []
        try:
            with engine.connect() as conn:
                sql_norm = llm_resp.sql.strip().rstrip(";")
                db_rows = conn.execute(sa_text(sql_norm)).fetchall()
                rows = [dict(r._mapping) for r in db_rows]
        except Exception as db_err:
            yield _sse("error", {"message": f"Query execution failed: {db_err}"})
            return

        yield _sse("data", {"rows": rows, "row_count": len(rows)})
        await asyncio.sleep(0)

        yield _sse("status", {"message": "Generating narrative…"})
        await asyncio.sleep(0)

        narrative = ""
        try:
            narrative = generate_narrative(
                question=question,
                sql=llm_resp.sql,
                result_data=rows,
                answer_type="table" if rows else "text",
                config=cfg,
            )
        except Exception:
            pass

        yield _sse("narrative", {"text": narrative})
        yield _sse("done", {"message": "Complete"})

    except Exception as e:
        logger.error(f"SSE stream error: {e}")
        yield _sse("error", {"message": str(e)})


@router.get("/chat/stream")
async def chat_stream(
    question: str = Query(...),
    plugin_id: str = Query(...),
    dataset_id: Optional[str] = Query(None),
):
    """
    SSE endpoint for streaming chat responses.
    Client usage:
      const es = new EventSource(`/chat/stream?question=...&plugin_id=...`)
      es.addEventListener('sql', e => console.log(JSON.parse(e.data)))
      es.addEventListener('data', e => console.log(JSON.parse(e.data)))
      es.addEventListener('narrative', e => console.log(JSON.parse(e.data)))
      es.addEventListener('done', () => es.close())
    """
    return StreamingResponse(
        _stream_chat_response(question, plugin_id, dataset_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── Report Builder ────────────────────────────────────────────────────────────


class ReportGoal(BaseModel):
    plugin_id: str
    dataset_id: Optional[str] = None
    goal: str  # e.g. "revenue performance last 30 days"
    sections: Optional[list[str]] = None  # e.g. ["trend", "top_segments", "forecast"]


@router.post("/agent/generate-report")
def generate_report(req: ReportGoal, db: Session = Depends(get_db)):
    """
    Autonomous report builder: given a goal, generates a structured report
    with SQL queries, results, and narrative for each requested section.
    """
    from app import nl_to_sql
    from app.llm_service import LLMConfig, generate_sql_with_llm, generate_narrative, SchemaContext

    t_start = time.time()
    cfg = LLMConfig()
    if not cfg.available:
        raise HTTPException(status_code=503, detail="LLM unavailable")

    plugin = nl_to_sql.PLUGIN_MANAGER.get_plugin(req.plugin_id) if nl_to_sql.PLUGIN_MANAGER else None
    if not plugin:
        # Try active plugin
        plugin = nl_to_sql.get_active_plugin()
    if not plugin:
        raise HTTPException(status_code=404, detail=f"Plugin '{req.plugin_id}' not found")

    sections_requested = req.sections or ["overview", "trend", "top_segments"]
    ctx = SchemaContext(
        plugin.schema,
        plugin.get_allowed_tables(),
        plugin.get_allowed_columns(),
        plugin_name=plugin.plugin_name,
    )

    report_sections = []
    for section in sections_requested:
        question = f"{req.goal} — {section} analysis"
        try:
            llm_resp = generate_sql_with_llm(question, ctx, cfg)
            if llm_resp is None or not llm_resp.sql:
                report_sections.append({"section": section, "status": "skipped", "reason": "no_sql"})
                continue

            sql_norm = llm_resp.sql.strip().rstrip(";")
            with engine.connect() as conn:
                from sqlalchemy import text as sa_text
                rows = conn.execute(sa_text(sql_norm)).fetchall()
                data = [dict(r._mapping) for r in rows]

            narrative = ""
            try:
                narrative = generate_narrative(question, llm_resp.sql, data, "table", cfg)
            except Exception:
                pass

            report_sections.append({
                "section": section,
                "question": question,
                "sql": llm_resp.sql,
                "data": data,
                "row_count": len(data),
                "narrative": narrative,
                "status": "ok",
            })
        except Exception as sec_err:
            logger.warning(f"Report section '{section}' failed: {sec_err}")
            report_sections.append({"section": section, "status": "error", "reason": str(sec_err)})

    elapsed_ms = int((time.time() - t_start) * 1000)
    return {
        "goal": req.goal,
        "plugin_id": req.plugin_id,
        "sections": report_sections,
        "generated_at": datetime.utcnow().isoformat(),
        "duration_ms": elapsed_ms,
    }
