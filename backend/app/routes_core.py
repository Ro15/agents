"""
Core API routes — the original endpoints for chat, upload, datasets,
plugins, insights, jobs, dashboard stats, and health.
"""
from __future__ import annotations

import io
import json
import logging
import math
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, List
from uuid import uuid4, UUID

import pandas as pd
from fastapi import APIRouter, File, UploadFile, HTTPException, Depends, Query, Header, BackgroundTasks, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import engine, SessionLocal
from app import nl_to_sql
from app.insight_engine import InsightEngine
from app.models import (
    SalesTransaction, IngestionRun, Dataset, Job, ColumnProfile, QueryFeedback, ConversationThread,
)
from app.helpers import (
    parse_uuid,
    get_last_updated,
    get_dataset_or_400,
    dataset_to_meta,
    ensure_active_plugin,
    record_audit_log,
    persist_generated_insights,
    fetch_latest_insights,
    maybe_answer_with_cached_insights,
    create_job,
    update_job_status,
)
from app.llm_service import (
    SchemaContext,
    LLMConfig,
    generate_sql_with_llm,
    generate_narrative,
    verify_sql_with_llm,
)
from app.sql_guard import SQLGuard, SQLGuardError
from app.routes_v2 import (
    check_rate_limit,
    log_llm_cost,
    record_query_history,
    save_conversation_message,
    get_conversation_history,
    get_conversation_memory_context,
)
from cache.cache import stable_hash, cache_get, cache_set, DB_RESULT_CACHE_TTL_SECONDS

logger = logging.getLogger(__name__)

router = APIRouter()

# Insight engine cache keyed by plugin name
INSIGHT_ENGINES: dict[str, InsightEngine] = {}

# imports for universal ingestion pipeline
from app.file_storage import save_file as archive_file
from app.parsers import parse_file, SUPPORTED_EXTENSIONS
from app.ingestion_service import run_ingestion_pipeline

_NUM_PATTERN = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def _extract_numbers(text_value: str) -> list[float]:
    vals: list[float] = []
    if not text_value:
        return vals
    for tok in _NUM_PATTERN.findall(text_value):
        try:
            vals.append(float(tok.replace(",", "")))
        except Exception:
            continue
    return vals


def _answer_numbers(answer, answer_type: str, max_vals: int = 200) -> list[float]:
    vals: list[float] = []
    if answer_type == "number":
        try:
            return [float(answer)]
        except Exception:
            return []
    if answer_type != "table" or not isinstance(answer, list):
        return []
    for row in answer:
        if not isinstance(row, dict):
            continue
        for v in row.values():
            if isinstance(v, (int, float)) and len(vals) < max_vals:
                vals.append(float(v))
            if len(vals) >= max_vals:
                return vals
    return vals


def _narrative_supported_by_answer(narrative: str, answer, answer_type: str) -> bool:
    narrative_nums = _extract_numbers(narrative)
    if not narrative_nums:
        return True
    answer_nums = _answer_numbers(answer, answer_type)
    if not answer_nums:
        return False
    for n in narrative_nums:
        matched = any(abs(n - a) <= max(1e-6, abs(a) * 0.01) for a in answer_nums)
        if not matched:
            return False
    return True


def _tokenize_words(text_value: str) -> set[str]:
    return {t for t in re.findall(r"[a-zA-Z][a-zA-Z0-9_]+", (text_value or "").lower()) if len(t) > 2}


def _is_followup_question(question: str) -> bool:
    q = (question or "").strip().lower()
    if not q:
        return False
    markers = (
        "and ",
        "what about",
        "how about",
        "same for",
        "also",
        "then",
        "now",
        "for that",
        "for this",
        "compare that",
    )
    pronouns = ("it", "that", "those", "them", "this", "same")
    return q.startswith(markers) or any(re.search(rf"\b{p}\b", q) for p in pronouns)


def _resolve_followup_question(question: str, conversation_history: List[dict]) -> str:
    """
    Expand short/elliptical follow-ups with the most recent user/assistant context.
    """
    q = (question or "").strip()
    if not q or not conversation_history or not _is_followup_question(q):
        return q
    last_user = ""
    last_assistant = ""
    for turn in reversed(conversation_history):
        role = (turn.get("role") or "").lower()
        content = (turn.get("content") or "").strip()
        if not content:
            continue
        if role == "assistant" and not last_assistant:
            last_assistant = content[:600]
        if role == "user" and not last_user:
            last_user = content[:600]
        if last_user and last_assistant:
            break
    if not last_user and not last_assistant:
        return q
    context_bits = []
    if last_user:
        context_bits.append(f"Previous user question: {last_user}")
    if last_assistant:
        context_bits.append(f"Previous assistant answer: {last_assistant}")
    return f"{q}\n\nFollow-up context:\n" + "\n".join(context_bits)


def _maybe_clarification_response(
    question: str,
    conversation_history: List[dict],
    plugin_name: str,
    last_updated,
):
    """
    Clarification gate: ask one clear question instead of guessing on ambiguous prompts.
    """
    intent = nl_to_sql.classify_intent(question)
    if intent == "unsupported":
        return {
            "answer_type": "text",
            "answer": "I can help with data analysis questions only. Please ask about metrics, trends, segments, or comparisons.",
            "explanation": "unsupported_intent",
            "sql": None,
            "data_last_updated": last_updated,
            "confidence": "low",
            "plugin": plugin_name,
            "assumptions": [],
            "requires_clarification": True,
        }
    if intent != "needs_clarification":
        return None
    # If there is recent context, allow follow-up resolution to proceed.
    if conversation_history and len(conversation_history) >= 2:
        return None
    return {
        "answer_type": "text",
        "answer": (
            "I can do that. Please add one detail: metric, dimension, and time window.\n"
            "Example: 'Show total revenue by category for last 30 days.'"
        ),
        "explanation": "clarification_required",
        "sql": None,
        "data_last_updated": last_updated,
        "confidence": "low",
        "plugin": plugin_name,
        "assumptions": [],
        "requires_clarification": True,
    }


def _score_column_relevance(question: str, column_name: str, description: str) -> float:
    q_tokens = _tokenize_words(question)
    if not q_tokens:
        return 0.0
    field = f"{column_name or ''} {description or ''}".lower()
    score = 0.0
    for tok in q_tokens:
        if tok in field:
            score += 1.0
    # Prefer common analytical fields
    if re.search(r"(date|time|day|month|year)", column_name or "", re.I):
        score += 0.2
    if re.search(r"(amount|total|count|qty|quantity|price|cost|revenue|sales)", column_name or "", re.I):
        score += 0.2
    return score


def _select_relevant_dynamic_columns(question: str, col_profiles: list, max_cols: int = 20) -> list:
    scored = []
    for cp in col_profiles:
        score = _score_column_relevance(question, cp.column_name, cp.description or "")
        scored.append((score, cp))
    scored.sort(key=lambda x: x[0], reverse=True)
    top = [cp for score, cp in scored if score > 0][:max_cols]
    if not top:
        top = col_profiles[:max_cols]
    # Ensure time column is present if available
    for cp in col_profiles:
        dt = (cp.data_type or "").lower()
        if ("date" in dt or "time" in dt) and cp not in top:
            top.append(cp)
            break
    return top[:max_cols]


def _build_dynamic_glossary(columns: list, max_entries: int = 25) -> list[dict]:
    glossary = []
    for cp in columns:
        term = (cp.column_name or "").replace("_", " ").strip()
        meaning = (cp.description or "").strip()
        if term and meaning:
            glossary.append({"term": term, "definition": meaning})
        if len(glossary) >= max_entries:
            break
    return glossary


def _build_feedback_learning_context(db: Session, plugin_id: str, question: str, limit: int = 5) -> str:
    """
    Use prior corrected SQL feedback as learning context for similar questions.
    """
    rows = db.query(QueryFeedback).filter(
        QueryFeedback.plugin_id == plugin_id,
        QueryFeedback.corrected_sql.isnot(None),
    ).order_by(QueryFeedback.created_at.desc()).limit(50).all()
    if not rows:
        return ""
    q_tokens = _tokenize_words(question)
    ranked = []
    for row in rows:
        row_tokens = _tokenize_words((row.question or "") + " " + (row.comment or ""))
        overlap = len(q_tokens.intersection(row_tokens))
        ranked.append((overlap, row))
    ranked.sort(key=lambda x: x[0], reverse=True)
    picked = [r for score, r in ranked if score > 0][:limit]
    if not picked:
        picked = [r for _, r in ranked[:2]]
    lines = []
    for r in picked:
        lines.append(f"- User asked: {r.question}")
        if r.original_sql:
            lines.append(f"  Original SQL: {r.original_sql}")
        lines.append(f"  Corrected SQL: {r.corrected_sql}")
        if r.comment:
            lines.append(f"  Note: {r.comment}")
    return "\n".join(lines)


def _confidence_to_score(conf: str) -> int:
    return {"low": 1, "medium": 2, "high": 3}.get((conf or "").lower(), 2)


def _score_to_confidence(score: int) -> str:
    if score >= 3:
        return "high"
    if score <= 1:
        return "low"
    return "medium"


def _result_sanity_warnings(question: str, answer_type: str, answer) -> List[str]:
    warnings: List[str] = []
    q = (question or "").lower()
    if answer_type == "table" and isinstance(answer, list) and len(answer) == 0:
        warnings.append("Query returned no rows for the requested filters.")
    if answer_type == "number":
        try:
            val = float(answer)
            if math.isnan(val) or math.isinf(val):
                warnings.append("Result is not a finite numeric value.")
            if re.search(r"(percent|percentage|rate|ratio)", q) and abs(val) > 1000:
                warnings.append("Result magnitude is unusually high for a rate/percentage.")
        except Exception:
            warnings.append("Numeric answer could not be validated.")
    return warnings


# ── Dependencies ────────────────────────────────────────────────────────

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_insight_engine_for_plugin(plugin_name: str) -> InsightEngine:
    if plugin_name not in INSIGHT_ENGINES:
        active_plugin = ensure_active_plugin(plugin_name)
        INSIGHT_ENGINES[plugin_name] = InsightEngine(active_plugin)
    return INSIGHT_ENGINES[plugin_name]


# ── Pydantic models ────────────────────────────────────────────────────

class ChatQuery(BaseModel):
    query: str
    plugin: str = "restaurant"
    dataset_id: Optional[str] = None
    conversation_id: Optional[str] = None
    conversation_history: Optional[List[dict]] = None


class PluginSwitchRequest(BaseModel):
    plugin: str


class InsightRunRequest(BaseModel):
    plugin: Optional[str] = None
    dataset_id: Optional[str] = None
    limit: Optional[int] = 20


# ── Insights ────────────────────────────────────────────────────────────

@router.post("/insights/run")
def run_insights(request: InsightRunRequest, db: Session = Depends(get_db)):
    t0 = time.time()
    try:
        active_plugin = ensure_active_plugin(request.plugin)
        ds = get_dataset_or_400(db, request.dataset_id, active_plugin.plugin_name)
        ie = get_insight_engine_for_plugin(active_plugin.plugin_name)
        generated = ie.run_all_insights(db, dataset_id=str(ds.dataset_id))
        if request.limit:
            generated = generated[: request.limit]
        run_id = persist_generated_insights(db, generated, active_plugin.plugin_name, request.dataset_id) if generated else None
        record_audit_log(
            db, plugin_id=active_plugin.plugin_name, dataset_id=request.dataset_id,
            user_question="insights_run", intent="insights_run", generated_sql=None,
            sql_valid=True, execution_ms=int((time.time() - t0) * 1000),
            rows_returned=len(generated), confidence="medium", failure_reason=None, model_name=None,
        )
        return {"plugin": active_plugin.plugin_name, "run_id": run_id, "count": len(generated), "insights": [ie.to_dict(i) for i in generated]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error running insights: {e}")
        record_audit_log(
            db, plugin_id=request.plugin, dataset_id=request.dataset_id,
            user_question="insights_run", intent="insights_run", generated_sql=None,
            sql_valid=False, execution_ms=int((time.time() - t0) * 1000),
            rows_returned=None, confidence="low", failure_reason=str(e), model_name=None,
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/insights/latest")
def latest_insights(
    plugin: Optional[str] = Query(None),
    dataset_id: Optional[str] = Query(None),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    try:
        active_plugin = ensure_active_plugin(plugin)
        get_dataset_or_400(db, dataset_id, active_plugin.plugin_name)
        insights = fetch_latest_insights(db, active_plugin.plugin_name, dataset_id, limit)
        return {"plugin": active_plugin.plugin_name, "count": len(insights), "insights": insights}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving insights: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Upload ──────────────────────────────────────────────────────────────

@router.post("/upload/sales")
async def upload_sales_data(
    file: UploadFile = File(...),
    dataset_id: Optional[str] = Query(None),
    x_plugin: Optional[str] = Header(None),
    mode: str = Query("sync"),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db),
):
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="Invalid file type. Please upload a CSV file.")
    try:
        active_plugin = ensure_active_plugin(x_plugin)
        plugin_id = active_plugin.plugin_name
        try:
            dataset_uuid = uuid4() if dataset_id is None else UUID(str(dataset_id))
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid dataset_id format")
        contents = await file.read()
        df = pd.read_csv(io.BytesIO(contents))
        DEFAULT_COLUMN_MAPPING = {
            'order_id': 'order_id', 'order_datetime': 'order_datetime', 'item_name': 'item_name',
            'category': 'category', 'quantity': 'quantity', 'item_price': 'item_price',
            'total_line_amount': 'total_line_amount', 'payment_type': 'payment_type',
            'discount_amount': 'discount_amount', 'tax_amount': 'tax_amount',
        }
        REQUIRED_COLUMNS = ['order_id', 'order_datetime', 'item_name', 'quantity', 'item_price', 'total_line_amount']
        df.rename(columns=DEFAULT_COLUMN_MAPPING, inplace=True)
        missing_columns = [col for col in REQUIRED_COLUMNS if col not in df.columns]
        if missing_columns:
            raise HTTPException(status_code=400, detail=f"Missing required columns: {', '.join(missing_columns)}")
        df['order_datetime'] = pd.to_datetime(df['order_datetime'])
        df['dataset_id'] = dataset_uuid
        df['id'] = [uuid4() for _ in range(len(df))]
        df.to_sql(SalesTransaction.__tablename__, engine, if_exists='append', index=False)
        existing = db.query(Dataset).filter(Dataset.dataset_id == dataset_uuid).first()
        now_ts = datetime.utcnow()
        if existing:
            dataset_obj = existing
            dataset_obj.plugin_id = plugin_id
        else:
            dataset_obj = Dataset(
                dataset_id=dataset_uuid, plugin_id=plugin_id,
                dataset_name=os.path.splitext(file.filename)[0], created_at=now_ts,
            )
        dataset_obj.last_ingested_at = now_ts
        dataset_obj.row_count = len(df)
        dataset_obj.source_filename = file.filename
        dataset_obj.is_deleted = False
        dataset_obj.version = (dataset_obj.version or 1) + 1
        dataset_obj = db.merge(dataset_obj)
        ingestion_record = IngestionRun(
            dataset_name="sales", filename=file.filename, row_count=len(df),
            plugin_id=plugin_id, dataset_id=dataset_obj.dataset_id,
        )
        db.add(ingestion_record)
        db.commit()
        db.refresh(ingestion_record)
        db.refresh(dataset_obj)
        meta = dataset_to_meta(dataset_obj)
        meta["message"] = f"Successfully uploaded and ingested {len(df)} rows from {file.filename}."
        meta["ingested_at"] = ingestion_record.ingested_at.isoformat() if ingestion_record.ingested_at else None
        return meta
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error processing file {file.filename}: {e}")
        raise HTTPException(status_code=500, detail=f"An error occurred: {e}")


# ── Universal Upload (flexible schema) ──────────────────────────────────

@router.post("/upload")
async def upload_file_universal(
    file: UploadFile = File(...),
    dataset_name: Optional[str] = Query(None),
    dataset_id: Optional[str] = Query(None),
    plugin_id: Optional[str] = Query("default"),
    sheet_name: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Universal file upload.
    Accepts CSV, Excel (.xlsx/.xls), JSON, JSONL.
    Auto-detects schema, creates a dynamic table, archives the file.
    """
    ext = Path(file.filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
        )

    try:
        dataset_uuid = uuid4() if dataset_id is None else UUID(str(dataset_id))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid dataset_id format")

    contents = await file.read()
    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    try:
        # Archive the original file
        file_path = archive_file(str(dataset_uuid), file.filename, contents)

        # Parse into DataFrame
        sheet = int(sheet_name) if sheet_name and sheet_name.isdigit() else (sheet_name or None)
        df = parse_file(contents, file.filename, sheet_name=sheet)

        # Run shared ingestion pipeline (detect → create table → load → register)
        name = dataset_name or os.path.splitext(file.filename)[0]
        result = run_ingestion_pipeline(
            engine, db, df,
            dataset_id=dataset_uuid,
            plugin_id=plugin_id,
            name=name,
            source_filename=file.filename,
            file_path=str(file_path),
            file_format=ext.lstrip("."),
        )

        meta = dataset_to_meta(result.dataset)
        meta["message"] = f"Successfully uploaded {file.filename}: {result.rows_loaded} rows into {result.table_name}."
        meta["schema"] = [
            {"column": cs.name, "type": cs.pg_type, "nullable": cs.nullable,
             "sample_values": cs.sample_values[:3], "distinct_count": cs.distinct_count}
            for cs in result.column_schemas
        ]
        meta["load_errors"] = result.load_errors
        return meta

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        db.rollback()
        logger.error(f"Universal upload error for {file.filename}: {e}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {e}")


# ── Datasets ────────────────────────────────────────────────────────────

@router.get("/datasets")
def list_datasets_endpoint(plugin_id: Optional[str] = Query(None), db: Session = Depends(get_db)):
    query = db.query(Dataset).filter(Dataset.is_deleted == False)  # noqa: E712
    if plugin_id:
        query = query.filter(Dataset.plugin_id == plugin_id)
    return [dataset_to_meta(ds) for ds in query.order_by(Dataset.created_at.desc()).all()]


@router.get("/datasets/{dataset_id}")
def get_dataset(dataset_id: str, db: Session = Depends(get_db)):
    ds_uuid = parse_uuid(dataset_id, "dataset_id")
    ds = db.query(Dataset).filter(Dataset.dataset_id == ds_uuid, Dataset.is_deleted == False).first()  # noqa: E712
    if not ds:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return dataset_to_meta(ds)


@router.delete("/datasets/{dataset_id}")
def soft_delete_dataset(dataset_id: str, db: Session = Depends(get_db)):
    ds_uuid = parse_uuid(dataset_id, "dataset_id")
    ds = db.query(Dataset).filter(Dataset.dataset_id == ds_uuid).first()
    if not ds:
        raise HTTPException(status_code=404, detail="Dataset not found")
    ds.is_deleted = True
    db.add(ds)
    db.commit()
    return {"status": "deleted", "dataset_id": dataset_id}


# ── Jobs ────────────────────────────────────────────────────────────────

@router.get("/jobs/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.job_id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id": str(job.job_id), "job_type": job.job_type, "plugin_id": job.plugin_id,
        "dataset_id": str(job.dataset_id) if job.dataset_id else None, "status": job.status,
        "created_at": job.created_at, "started_at": job.started_at, "finished_at": job.finished_at,
        "progress_pct": job.progress_pct, "result": job.result, "failure_reason": job.failure_reason,
    }


@router.get("/jobs")
def list_jobs(plugin_id: Optional[str] = None, status: Optional[str] = None, limit: int = 50, db: Session = Depends(get_db)):
    q = db.query(Job)
    if plugin_id:
        q = q.filter(Job.plugin_id == plugin_id)
    if status:
        q = q.filter(Job.status == status)
    return [
        {
            "job_id": str(j.job_id), "job_type": j.job_type, "status": j.status,
            "plugin_id": j.plugin_id, "dataset_id": str(j.dataset_id) if j.dataset_id else None,
            "created_at": j.created_at, "result": j.result, "failure_reason": j.failure_reason,
        }
        for j in q.order_by(Job.created_at.desc()).limit(limit).all()
    ]


# ── Chat ────────────────────────────────────────────────────────────────

@router.post("/chat")
def chat_endpoint(chat_query: ChatQuery, request: Request = None, db: Session = Depends(get_db)):
    # Rate limiting
    client_ip = request.client.host if request and request.client else "unknown"
    if not check_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Please wait before sending more requests.")

    last_updated = get_last_updated(db)
    t0 = time.time()
    generated_sql = None

    try:
        def _row_to_dict(row) -> dict:
            if isinstance(row, dict):
                return row
            mapping = getattr(row, "_mapping", None)
            if mapping is not None:
                return dict(mapping)
            return dict(row)

        active_plugin = ensure_active_plugin(chat_query.plugin)
        dataset_id = chat_query.dataset_id
        ds = get_dataset_or_400(db, dataset_id, active_plugin.plugin_name)
        dataset_version = ds.version
        is_dynamic = getattr(ds, "schema_type", "static") == "dynamic"

        # Multi-turn: resolve conversation history
        conversation_history = chat_query.conversation_history or []
        thread_id = None
        if chat_query.conversation_id:
            try:
                thread_id = UUID(str(chat_query.conversation_id))
                if not conversation_history:
                    conversation_history = get_conversation_history(db, thread_id)
                memory_context = get_conversation_memory_context(db, thread_id)
                if memory_context:
                    conversation_history = (memory_context + conversation_history)[-16:]
            except Exception:
                logger.debug(f"Invalid conversation_id: {chat_query.conversation_id}")
        elif os.getenv("CHAT_AUTO_CREATE_SESSION", "true").lower() in {"1", "true", "yes"}:
            try:
                thread = ConversationThread(
                    plugin_id=active_plugin.plugin_name,
                    dataset_id=str(ds.dataset_id) if ds else None,
                    title=(chat_query.query or "").strip()[:60] or "New conversation",
                )
                db.add(thread)
                db.commit()
                db.refresh(thread)
                thread_id = thread.thread_id
            except Exception as e:
                logger.warning(f"Auto-create conversation thread failed: {e}")

        resolved_query = _resolve_followup_question(chat_query.query, conversation_history)
        clarification = _maybe_clarification_response(
            resolved_query, conversation_history, active_plugin.plugin_name, last_updated
        )
        if clarification:
            if thread_id:
                try:
                    save_conversation_message(db, thread_id, "user", chat_query.query)
                    save_conversation_message(
                        db,
                        thread_id,
                        "assistant",
                        clarification.get("answer") or "",
                        answer_type="text",
                        payload=clarification,
                    )
                except Exception as e:
                    logger.warning(f"Conversation persistence failed for clarification path: {e}")
            clarification["conversation_id"] = str(thread_id) if thread_id else None
            return clarification

        learning_context = _build_feedback_learning_context(db, active_plugin.plugin_name, resolved_query)

        # Try cached insights first (static datasets only)
        if not is_dynamic:
            cached_response = maybe_answer_with_cached_insights(resolved_query, active_plugin.plugin_name, dataset_id, db, last_updated)
            if cached_response:
                return cached_response
        dynamic_context = None
        dynamic_guard = None
        dynamic_time_column = None
        static_schema_context = None
        static_glossary = (
            active_plugin.get_business_glossary()
            if hasattr(active_plugin, "get_business_glossary")
            else []
        )
        if not is_dynamic:
            static_schema_context = SchemaContext(
                active_plugin.schema,
                active_plugin.get_allowed_tables(),
                active_plugin.get_allowed_columns(),
                plugin_name=active_plugin.plugin_name,
                metrics_description=active_plugin.get_metrics_description(),
                views=getattr(active_plugin, "compiled_views", []),
                business_glossary=static_glossary,
                relationships_description=active_plugin.get_relationships_description(),
                schema_description=active_plugin.get_schema_description(),
            )
        if is_dynamic:
            col_profiles = db.query(ColumnProfile).filter(
                ColumnProfile.dataset_id == ds.dataset_id
            ).order_by(ColumnProfile.column_name).all()
            if not col_profiles:
                raise HTTPException(status_code=400, detail="Dynamic dataset schema profile is missing. Re-upload data and retry.")
            selected_profiles = _select_relevant_dynamic_columns(
                resolved_query,
                col_profiles,
                max_cols=int(os.getenv("DYNAMIC_PROMPT_MAX_COLUMNS", "20")),
            )
            dynamic_cols = [
                {"column_name": cp.column_name, "data_type": cp.data_type, "description": cp.description or ""}
                for cp in selected_profiles
            ]
            dyn_table = ds.table_name
            if not dyn_table:
                raise HTTPException(status_code=400, detail="Dynamic dataset table is missing.")

            allowed_cols = {cp.column_name for cp in col_profiles}
            dynamic_context = SchemaContext(
                schema={},
                allowed_tables={dyn_table},
                allowed_columns=allowed_cols,
                plugin_name=active_plugin.plugin_name,
                dynamic_columns=dynamic_cols,
                dynamic_table=dyn_table,
                focus_columns=[cp.column_name for cp in selected_profiles],
                business_glossary=_build_dynamic_glossary(selected_profiles),
            )
            dynamic_guard = SQLGuard(
                {dyn_table.lower()},
                {c.lower() for c in allowed_cols},
            )
            for cp in col_profiles:
                dtype = (cp.data_type or "").lower()
                if "date" in dtype or "time" in dtype:
                    dynamic_time_column = cp.column_name
                    break

        def _serialize_val(v):
            return str(v) if isinstance(v, UUID) else v

        def _serialize_payload(payload):
            if payload.get("type") == "scalar":
                return {"type": "scalar", "value": _serialize_val(payload.get("value")), "row_count": payload.get("row_count", 1)}
            if payload.get("type") == "table":
                rows = payload.get("rows", [])
                return {"type": "table", "rows": [{k: _serialize_val(v) for k, v in _row_to_dict(r).items()} for r in rows], "row_count": payload.get("row_count", len(rows))}
            return payload

        def _generate(feedback: Optional[dict] = None, use_cache: bool = True):
            if is_dynamic:
                cfg = LLMConfig()
                today_iso = datetime.utcnow().date().isoformat()
                llm_resp = generate_sql_with_llm(
                    resolved_query,
                    dynamic_context,
                    cfg,
                    feedback=feedback,
                    extra_context=learning_context,
                    timezone=os.getenv("LLM_TIMEZONE", "UTC"),
                    today_iso=today_iso,
                    conversation_history=conversation_history,
                )
                if llm_resp is None:
                    raise ValueError("LLM failed to generate SQL for this question")
                candidate_sql = nl_to_sql.normalize_sql(
                    nl_to_sql.clamp_date_range(
                        nl_to_sql.fix_date_literal_intervals(llm_resp.sql),
                        dynamic_time_column,
                        active_plugin.policy.max_date_range_days if active_plugin.policy else None,
                    )
                )
                dynamic_guard.validate(candidate_sql)
                return nl_to_sql.SQLGenerationResult(
                    sql=candidate_sql,
                    answer_type=llm_resp.answer_type,
                    assumptions=llm_resp.assumptions or [],
                    confidence="high",
                    intent="analytics_query",
                    repairs=0,
                    model_name=llm_resp.model_name,
                    failure_reason=None,
                    cache_info={"llm_cache_hit": False},
                    chart_hint=llm_resp.chart_hint,
                    summary=llm_resp.summary,
                )
            return nl_to_sql.generate_sql(
                resolved_query,
                dataset_id=str(ds.dataset_id),
                dataset_version=dataset_version,
                conversation_history=conversation_history,
                feedback=feedback,
                learning_context=learning_context,
                business_glossary=static_glossary,
                use_cache=use_cache,
            )

        generation = None
        scoped_sql = None
        result_payload = None
        db_cache_hit = False
        db_key = ""
        execution_feedback = None
        max_exec_attempts = int(os.getenv("CHAT_SQL_MAX_ATTEMPTS", "3"))

        for exec_attempt in range(max_exec_attempts):
            try:
                generation = _generate(feedback=execution_feedback, use_cache=execution_feedback is None)
                generated_sql = generation.sql
            except (SQLGuardError, ValueError) as e:
                logger.warning(f"SQL generation attempt {exec_attempt + 1} failed: {e}")
                if exec_attempt + 1 >= max_exec_attempts:
                    raise
                execution_feedback = {
                    "error": f"generation_failed: {e}",
                    "allowed_tables": list(active_plugin.get_allowed_tables()) if not is_dynamic else list(dynamic_context.allowed_tables),
                    "allowed_columns": list(active_plugin.get_allowed_columns()) if not is_dynamic else list(dynamic_context.allowed_columns),
                    "time_column": active_plugin.primary_time_column() if not is_dynamic else dynamic_time_column,
                    "learning_examples": learning_context,
                }
                continue

            # Confidence gate for ambiguous questions: ask for clarification instead of guessing.
            if generation.confidence == "low" and nl_to_sql.classify_intent(resolved_query) == "needs_clarification":
                clarification_payload = {
                    "answer_type": "text",
                    "answer": "Please clarify the metric, dimension, or date range so I can answer accurately.",
                    "explanation": generation.failure_reason or "low_confidence_clarification",
                    "sql": None,
                    "data_last_updated": last_updated,
                    "confidence": "low",
                    "plugin": active_plugin.plugin_name,
                    "assumptions": generation.assumptions,
                    "requires_clarification": True,
                    "conversation_id": str(thread_id) if thread_id else None,
                }
                if thread_id:
                    try:
                        save_conversation_message(db, thread_id, "user", chat_query.query)
                        save_conversation_message(
                            db,
                            thread_id,
                            "assistant",
                            clarification_payload["answer"],
                            answer_type="text",
                            payload=clarification_payload,
                        )
                    except Exception as e:
                        logger.warning(f"Conversation persistence failed for low-confidence path: {e}")
                return clarification_payload

            if generation.intent != "analytics_query" or not generated_sql:
                record_audit_log(
                    db, plugin_id=active_plugin.plugin_name, dataset_id=dataset_id,
                    user_question=chat_query.query, intent=generation.intent, generated_sql=None,
                    sql_valid=False, execution_ms=int((time.time() - t0) * 1000),
                    rows_returned=None, confidence=generation.confidence,
                    failure_reason=generation.failure_reason or "unsupported_intent",
                    model_name=generation.model_name,
                )
                return {
                    "answer_type": "text",
                    "answer": "I need more context to answer that. Please ask a data question related to the plugin.",
                    "explanation": generation.failure_reason or "Question not supported.",
                    "sql": None, "data_last_updated": last_updated,
                    "confidence": generation.confidence, "plugin": active_plugin.plugin_name,
                    "assumptions": generation.assumptions,
                }

            try:
                if os.getenv("LLM_SQL_VERIFIER_ENABLED", "true").lower() in {"1", "true", "yes"}:
                    verifier_context = dynamic_context if is_dynamic else static_schema_context
                    verifier_result = verify_sql_with_llm(
                        question=resolved_query,
                        sql=generated_sql,
                        schema_context=verifier_context,
                        config=LLMConfig(),
                    )
                    if not verifier_result.get("approved", True):
                        corrected_sql = verifier_result.get("corrected_sql")
                        reason = verifier_result.get("reason") or "sql_verifier_rejected"
                        if corrected_sql:
                            generated_sql = corrected_sql
                        else:
                            raise ValueError(f"sql_verifier_rejected: {reason}")

                if is_dynamic:
                    scoped_sql = generated_sql
                else:
                    scoped_sql = nl_to_sql.SQL_GUARD.enforce_dataset_filter(generated_sql, "dataset_id")
                scoped_sql = re.sub(
                    r"DATE\('(\d{4}-\d{2}-\d{2})'\s*-\s*INTERVAL\s*'(\d+\s+day[s]?)'\)",
                    r"(DATE '\1' - INTERVAL '\2')", scoped_sql, flags=re.IGNORECASE,
                )

                params = {} if is_dynamic else {"dataset_id": ds.dataset_id}
                hash_params = {} if is_dynamic else {"dataset_id": str(ds.dataset_id)}
                sql_norm = scoped_sql.strip().rstrip(";")
                db_key = stable_hash({"ds": str(ds.dataset_id), "v": dataset_version, "sql": sql_norm, "params": hash_params})

                cached = cache_get("db_result", db_key)
                if cached is not None:
                    db_cache_hit = True
                    result_payload = _serialize_payload(cached)
                    break

                with db.get_bind().connect() as conn:
                    conn.execute(text("SET statement_timeout = '5s';"))
                    rows = conn.execute(text(sql_norm), params).fetchall()
                if len(rows) == 1 and len(rows[0]) == 1:
                    result_payload = {"type": "scalar", "value": _serialize_val(rows[0][0]), "row_count": 1}
                else:
                    result_payload = {
                        "type": "table",
                        "rows": [{k: _serialize_val(v) for k, v in _row_to_dict(r).items()} for r in rows],
                        "row_count": len(rows),
                    }
                cache_set("db_result", db_key, _serialize_payload(result_payload), DB_RESULT_CACHE_TTL_SECONDS)
                break
            except (SQLGuardError, Exception) as e:
                logger.warning(f"SQL attempt {exec_attempt + 1} failed: {e}")
                if exec_attempt + 1 >= max_exec_attempts:
                    raise
                execution_feedback = {
                    "error": f"execution_failed: {e}",
                    "allowed_tables": list(active_plugin.get_allowed_tables()) if not is_dynamic else list(dynamic_context.allowed_tables),
                    "allowed_columns": list(active_plugin.get_allowed_columns()) if not is_dynamic else list(dynamic_context.allowed_columns),
                    "time_column": active_plugin.primary_time_column() if not is_dynamic else dynamic_time_column,
                    "learning_examples": learning_context,
                }

        if result_payload is None:
            raise ValueError("SQL execution failed after retries")

        derived_answer_type = "number" if result_payload["type"] == "scalar" else "table"
        answer_type = generation.answer_type or derived_answer_type
        # Keep response shape consistent with executed SQL payload.
        if result_payload["type"] == "table" and answer_type != "table":
            answer_type = "table"
        elif result_payload["type"] == "scalar" and answer_type == "table":
            answer_type = "number"
        if result_payload["type"] == "scalar":
            val = result_payload["value"]
            answer = 0 if val is None else val
        else:
            answer = result_payload["rows"]

        sanity_warnings = _result_sanity_warnings(resolved_query, answer_type, answer)
        confidence_score = _confidence_to_score(generation.confidence)
        if sanity_warnings:
            confidence_score -= 1
        final_confidence = _score_to_confidence(confidence_score)

        exec_ms = int((time.time() - t0) * 1000)
        record_audit_log(
            db, plugin_id=active_plugin.plugin_name, dataset_id=dataset_id,
            user_question=chat_query.query, intent=generation.intent, generated_sql=scoped_sql,
            sql_valid=True, execution_ms=exec_ms, rows_returned=result_payload["row_count"],
            confidence=final_confidence, failure_reason=None, model_name=generation.model_name,
        )

        # Chart hint
        chart_hint = getattr(generation, "chart_hint", "none") or "none"
        summary = getattr(generation, "summary", "") or ""
        if chart_hint == "none" and answer_type == "table" and isinstance(answer, list) and len(answer) > 0:
            cols = list(answer[0].keys())
            time_keywords = {"date", "day", "month", "year", "week", "hour", "time", "period", "quarter"}
            has_time = any(any(kw in c.lower() for kw in time_keywords) for c in cols)
            num_cols = [c for c in cols if isinstance(answer[0].get(c), (int, float))]
            if has_time:
                chart_hint = "line" if len(num_cols) <= 1 else "area"
            elif len(answer) <= 8 and len(num_cols) == 1:
                chart_hint = "pie"
            elif len(num_cols) >= 1:
                chart_hint = "bar"
        if not summary:
            if answer_type == "table" and isinstance(answer, list):
                summary = f"Returned {len(answer)} rows."
            elif answer_type == "number":
                summary = f"The result is {answer}."
        if sanity_warnings:
            summary = (summary + " " if summary else "") + f"Sanity check: {sanity_warnings[0]}"

        # Narrative generation
        narrative = ""
        try:
            cfg = LLMConfig()
            if cfg.available:
                narrative = generate_narrative(question=chat_query.query, sql=scoped_sql, result_data=answer, answer_type=answer_type, config=cfg)
                input_est = len(chat_query.query) // 4 + len(scoped_sql) // 4 + 200
                output_est = len(narrative) // 4 if narrative else 0
                log_llm_cost(db, active_plugin.plugin_name, cfg.model, input_est, output_est, "/chat/narrative")
        except Exception as e:
            logger.warning(f"Narrative generation skipped: {e}")
        if narrative and not _narrative_supported_by_answer(narrative, answer, answer_type):
            logger.warning("Narrative claim-check failed; falling back to deterministic summary.")
            narrative = ""

        # Record query history
        history_id = None
        try:
            history_id = record_query_history(
                db, plugin_id=active_plugin.plugin_name, dataset_id=dataset_id,
                question=chat_query.query, sql=scoped_sql, answer_type=answer_type,
                answer_summary=narrative or summary, confidence=final_confidence,
            )
        except Exception as e:
            logger.warning(f"Query history recording failed: {e}")

        response_payload = {
            "answer_type": answer_type,
            "answer": answer,
            "summary": summary,
            "narrative": narrative,
            "chart_hint": chart_hint,
            "sql": scoped_sql,
            "confidence": final_confidence,
            "plugin": active_plugin.plugin_name,
            "assumptions": generation.assumptions + sanity_warnings,
        }

        # Multi-turn: persist messages
        if thread_id:
            try:
                save_conversation_message(db, thread_id, "user", chat_query.query)
                save_conversation_message(
                    db,
                    thread_id,
                    "assistant",
                    narrative or summary or str(answer)[:500],
                    sql=scoped_sql,
                    answer_type=answer_type,
                    payload=response_payload,
                )
            except Exception as e:
                logger.warning(f"Conversation message persistence failed: {e}")

        # LLM cost tracking for SQL generation
        try:
            _cfg = LLMConfig()
            log_llm_cost(db, active_plugin.plugin_name, _cfg.model, len(chat_query.query) // 4 + 300, len(scoped_sql) // 4 if scoped_sql else 0, "/chat/sql")
        except Exception:
            pass

        return {
            "answer_type": answer_type, "answer": answer, "explanation": "Validated SQL executed against dataset.",
            "summary": summary, "narrative": narrative, "chart_hint": chart_hint, "sql": scoped_sql,
            "data_last_updated": last_updated, "confidence": final_confidence,
            "plugin": active_plugin.plugin_name, "assumptions": generation.assumptions + sanity_warnings,
            "dataset_filter_enforced": True,
            "conversation_id": str(thread_id) if thread_id else None,
            "history_id": str(history_id) if history_id else None,
            "sanity_warnings": sanity_warnings,
            "cache": {
                "llm_sql": {"hit": generation.cache_info.get("llm_cache_hit", False), "key": generation.cache_info.get("llm_cache_key")},
                "db_result": {"hit": db_cache_hit, "key": db_key[:8]},
            },
        }

    except HTTPException:
        raise
    except ValueError as e:
        record_audit_log(
            db, plugin_id=chat_query.plugin, dataset_id=chat_query.dataset_id,
            user_question=chat_query.query, intent="analytics_query", generated_sql=generated_sql,
            sql_valid=False, execution_ms=int((time.time() - t0) * 1000),
            rows_returned=None, confidence="low", failure_reason=str(e), model_name=None,
        )
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error during chat processing: {e}")
        record_audit_log(
            db, plugin_id=chat_query.plugin, dataset_id=chat_query.dataset_id,
            user_question=chat_query.query, intent="analytics_query", generated_sql=generated_sql,
            sql_valid=False, execution_ms=int((time.time() - t0) * 1000),
            rows_returned=None, confidence="low", failure_reason=str(e), model_name=None,
        )
        return {
            "answer": "I'm sorry, but I encountered an error trying to answer your question.",
            "confidence": "low", "sql": generated_sql, "explanation": str(e),
            "plugin": None, "dataset_filter_enforced": True,
        }


# ── Plugins ─────────────────────────────────────────────────────────────

@router.post("/plugin/switch")
def switch_plugin(req: PluginSwitchRequest):
    try:
        if nl_to_sql.set_active_plugin(req.plugin):
            active_plugin = nl_to_sql.get_active_plugin()
            return {"status": "success", "plugin": active_plugin.plugin_name, "tables": list(active_plugin.get_allowed_tables()), "metrics": list(active_plugin.metrics.keys())}
        raise HTTPException(status_code=404, detail=f"Plugin '{req.plugin}' not found")
    except Exception as e:
        logger.error(f"Error switching plugin: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/plugins")
def list_plugins():
    try:
        summaries = nl_to_sql.PLUGIN_MANAGER.list_summaries() if nl_to_sql.PLUGIN_MANAGER else []
        active_plugin = nl_to_sql.ACTIVE_PLUGIN.plugin_name if nl_to_sql.ACTIVE_PLUGIN else None
        return {"plugins": summaries, "active_plugin": active_plugin}
    except Exception as e:
        logger.error(f"Error listing plugins: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/plugins/{plugin_id}")
def get_plugin_detail(plugin_id: str):
    try:
        plugin = nl_to_sql.PLUGIN_MANAGER.get_plugin(plugin_id) if nl_to_sql.PLUGIN_MANAGER else None
        if not plugin:
            raise HTTPException(status_code=404, detail="Plugin not found")
        defn = plugin.to_definition()
        return {
            "id": defn.id, "name": defn.name, "description": defn.description, "domains": defn.domains,
            "required_columns": defn.required_columns, "sample_csvs": defn.sample_csvs,
            "tables": list(defn.tables.keys()), "primary_time_column": defn.primary_time_column,
            "metrics": list(defn.metrics.keys()), "question_packs": list(defn.question_packs.keys()),
            "policy": defn.policy.__dict__ if defn.policy else {},
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting plugin detail: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/plugins/{plugin_id}/views")
def get_plugin_views(plugin_id: str):
    try:
        plugin = nl_to_sql.PLUGIN_MANAGER.get_plugin(plugin_id) if nl_to_sql.PLUGIN_MANAGER else None
        if not plugin:
            raise HTTPException(status_code=404, detail="Plugin not found")
        return {"plugin": plugin_id, "views": getattr(plugin, "compiled_views", [])}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/plugins/{plugin_id}/questions")
def get_plugin_questions(plugin_id: str):
    try:
        plugin = nl_to_sql.PLUGIN_MANAGER.get_plugin(plugin_id) if nl_to_sql.PLUGIN_MANAGER else None
        if not plugin:
            raise HTTPException(status_code=404, detail="Plugin not found")
        return [
            {"id": name, "title": pack.description or name, "questions": [p.pattern for p in pack.patterns]}
            for name, pack in plugin.question_packs.items()
        ]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/plugins/{plugin_id}/glossary")
def get_plugin_glossary(plugin_id: str):
    try:
        plugin = nl_to_sql.PLUGIN_MANAGER.get_plugin(plugin_id) if nl_to_sql.PLUGIN_MANAGER else None
        if not plugin:
            raise HTTPException(status_code=404, detail="Plugin not found")
        glossary = plugin.get_business_glossary() if hasattr(plugin, "get_business_glossary") else []
        return {"plugin": plugin_id, "glossary": glossary}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/plugin/info")
def get_plugin_info():
    try:
        active_plugin = nl_to_sql.get_active_plugin()
        return {
            "plugin_name": active_plugin.plugin_name,
            "tables": list(active_plugin.get_allowed_tables()),
            "columns": list(active_plugin.get_allowed_columns()),
            "metrics": list(active_plugin.metrics.keys()),
            "question_packs": list(active_plugin.question_packs.keys()),
            "policy": {
                "allowed_question_types": active_plugin.policy.allowed_question_types,
                "forbidden_topics": active_plugin.policy.forbidden_topics,
                "enable_forecasting": active_plugin.policy.enable_forecasting,
                "enable_predictions": active_plugin.policy.enable_predictions,
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Dashboard stats ─────────────────────────────────────────────────────

@router.get("/dashboard/stats")
def get_dashboard_stats(
    plugin: str = Query(...),
    dataset_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    try:
        query_filter = "WHERE plugin_id = :plugin"
        params: dict = {"plugin": plugin}
        if dataset_id:
            query_filter += " AND dataset_id = :dsid"
            params["dsid"] = dataset_id

        row = db.execute(
            text(f"SELECT COUNT(*) AS cnt, "
                 f"ROUND(AVG(CASE WHEN confidence='high' THEN 3 WHEN confidence='medium' THEN 2 ELSE 1 END),1) AS avg_c "
                 f"FROM ai_audit_log {query_filter}"),
            params,
        ).fetchone()
        total_queries = int(row[0]) if row else 0
        avg_score = float(row[1]) if row and row[1] else 0
        avg_confidence = "high" if avg_score >= 2.5 else ("medium" if avg_score >= 1.5 else "low")

        total_rows = 0
        if dataset_id:
            ds_row = db.execute(text("SELECT row_count FROM datasets WHERE dataset_id = :dsid AND is_deleted = false"), {"dsid": dataset_id}).fetchone()
            total_rows = int(ds_row[0]) if ds_row and ds_row[0] else 0

        query_volume = []
        try:
            vol_rows = db.execute(
                text(f"SELECT DATE(created_at) AS d, COUNT(*) AS cnt FROM ai_audit_log {query_filter} GROUP BY DATE(created_at) ORDER BY d DESC LIMIT 14"),
                params,
            ).fetchall()
            query_volume = [{"date": str(r[0]), "count": int(r[1])} for r in reversed(vol_rows)]
        except Exception:
            pass

        recent_trend = []
        if dataset_id:
            try:
                trend_rows = db.execute(
                    text("SELECT DATE(order_datetime) AS d, SUM(quantity * item_price) AS rev FROM sales_transactions WHERE dataset_id = :dsid GROUP BY DATE(order_datetime) ORDER BY d LIMIT 30"),
                    {"dsid": dataset_id},
                ).fetchall()
                recent_trend = [{"date": str(r[0]), "value": float(r[1] or 0)} for r in trend_rows]
            except Exception:
                pass

        top_categories = []
        if dataset_id:
            try:
                cat_rows = db.execute(
                    text("SELECT COALESCE(category, 'Other') AS cat, SUM(quantity * item_price) AS rev FROM sales_transactions WHERE dataset_id = :dsid GROUP BY COALESCE(category, 'Other') ORDER BY rev DESC LIMIT 8"),
                    {"dsid": dataset_id},
                ).fetchall()
                top_categories = [{"name": str(r[0]), "value": float(r[1] or 0)} for r in cat_rows]
            except Exception:
                pass

        return {
            "total_rows": total_rows, "total_queries": total_queries,
            "avg_confidence": avg_confidence, "top_categories": top_categories,
            "recent_trend": recent_trend, "query_volume": query_volume,
        }
    except Exception as e:
        logger.error(f"Error computing dashboard stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Health ──────────────────────────────────────────────────────────────

@router.get("/")
def read_root():
    return {"message": "Restaurant Data Analyst Chat API is running."}


@router.get("/health")
def health_check(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        plugin_count = len(nl_to_sql.PLUGIN_MANAGER.plugins) if nl_to_sql.PLUGIN_MANAGER else 0
        return {"status": "ok", "database_connection": "successful", "plugins_loaded": plugin_count}
    except Exception as e:
        return {"status": "error", "database_connection": "failed", "error": str(e)}
