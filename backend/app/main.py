import os
import io
import json
import logging
import time
import traceback
from datetime import datetime
from typing import Optional, List
from uuid import uuid4, UUID
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, File, UploadFile, HTTPException, Depends, Query, Header, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, text, JSON as JSON_TYPE, ForeignKey, Boolean
from sqlalchemy import Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.types import Integer, String, TIMESTAMP, NUMERIC, UUID as UUID_TYPE, Text
from dataclasses import asdict

# Import NL-to-SQL logic
from app import nl_to_sql
from app.insight_engine import InsightEngine
from app.metrics.compiler import compile_metrics

# Load environment variables
load_dotenv()

# Database setup
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable not set")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Logging setup (structured-ish JSON)
logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","message":"%(message)s","module":"%(name)s"}',
)
logger = logging.getLogger(__name__)

# Insight engine cache keyed by plugin name
INSIGHT_ENGINES: dict[str, InsightEngine] = {}

# --- SQLAlchemy Models ---
class SalesTransaction(Base):
    __tablename__ = "sales_transactions"
    id = Column(UUID_TYPE(as_uuid=True), primary_key=True, default=uuid4)
    dataset_id = Column(UUID_TYPE(as_uuid=True), index=True, nullable=False)
    order_id = Column(String)
    order_datetime = Column(TIMESTAMP, index=True)
    item_name = Column(String, index=True)
    category = Column(String, nullable=True)
    quantity = Column(NUMERIC)
    item_price = Column(NUMERIC)
    total_line_amount = Column(NUMERIC)
    payment_type = Column(String, nullable=True)
    discount_amount = Column(NUMERIC, nullable=True)
    tax_amount = Column(NUMERIC, nullable=True)

class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    id = Column(UUID_TYPE(as_uuid=True), primary_key=True, default=uuid4)
    plugin_id = Column(String, index=True, nullable=True)
    dataset_id = Column(UUID_TYPE(as_uuid=True), index=True, nullable=True)
    dataset_name = Column(String)
    filename = Column(String)
    row_count = Column(Integer)
    ingested_at = Column(TIMESTAMP, server_default=text("now()"))


class InsightsRun(Base):
    __tablename__ = "insights_runs"
    run_id = Column(UUID_TYPE(as_uuid=True), primary_key=True, default=uuid4)
    plugin = Column(String, index=True)
    dataset_id = Column(String, nullable=True, index=True)
    generated_at = Column(TIMESTAMP, server_default=text("now()"), index=True)


class InsightsItem(Base):
    __tablename__ = "insights_items"
    id = Column(UUID_TYPE(as_uuid=True), primary_key=True, default=uuid4)
    run_id = Column(UUID_TYPE(as_uuid=True), ForeignKey("insights_runs.run_id", ondelete="CASCADE"), index=True)
    insight_id = Column(String, index=True)
    severity = Column(String)
    payload = Column(JSON_TYPE)  # full generated insight structure


class Dataset(Base):
    __tablename__ = "datasets"
    dataset_id = Column(UUID_TYPE(as_uuid=True), primary_key=True, default=uuid4)
    plugin_id = Column(String, index=True)
    dataset_name = Column(String, nullable=True)
    created_at = Column(TIMESTAMP, server_default=text("now()"))
    last_ingested_at = Column(TIMESTAMP, nullable=True)
    row_count = Column(Integer, nullable=True)
    source_filename = Column(String, nullable=True)
    is_deleted = Column(Boolean, server_default=text("false"))
    version = Column(Integer, nullable=False, server_default=text("1"))


class AIAuditLog(Base):
    __tablename__ = "ai_audit_log"
    id = Column(UUID_TYPE(as_uuid=True), primary_key=True, default=uuid4)
    created_at = Column(TIMESTAMP, server_default=text("now()"))
    plugin_id = Column(String, index=True, nullable=True)
    dataset_id = Column(String, index=True, nullable=True)
    user_question = Column(Text)
    intent = Column(String, nullable=True)
    generated_sql = Column(Text, nullable=True)
    sql_valid = Column(Boolean, nullable=True)
    execution_ms = Column(Integer, nullable=True)
    rows_returned = Column(Integer, nullable=True)
    confidence = Column(String, nullable=True)
    failure_reason = Column(Text, nullable=True)
    model_name = Column(String, nullable=True)
    prompt_version = Column(String, nullable=True)


class Job(Base):
    __tablename__ = "jobs"
    job_id = Column(UUID_TYPE(as_uuid=True), primary_key=True, default=uuid4)
    job_type = Column(String, nullable=False)
    plugin_id = Column(String, nullable=False)
    dataset_id = Column(UUID_TYPE(as_uuid=True), nullable=True)
    status = Column(String, nullable=False, default="QUEUED")
    created_at = Column(TIMESTAMP, server_default=text("now()"))
    started_at = Column(TIMESTAMP, nullable=True)
    finished_at = Column(TIMESTAMP, nullable=True)
    progress_pct = Column(Integer, nullable=True)
    payload = Column(JSON_TYPE, nullable=False)
    result = Column(JSON_TYPE, nullable=True)
    failure_reason = Column(Text, nullable=True)
    failure_trace = Column(Text, nullable=True)


# Indexes for dataset scoping
Index("idx_sales_transactions_dataset_time", SalesTransaction.dataset_id, SalesTransaction.order_datetime)
Index("idx_sales_transactions_dataset_item", SalesTransaction.dataset_id, SalesTransaction.item_name)

# --- Pydantic Models ---
class ChatQuery(BaseModel):
    query: str
    plugin: str = "restaurant"  # Default plugin
    dataset_id: Optional[str] = None

class PluginSwitchRequest(BaseModel):
    plugin: str

class InsightRunRequest(BaseModel):
    plugin: Optional[str] = None
    dataset_id: Optional[str] = None
    limit: Optional[int] = 20


class DatasetMeta(BaseModel):
    dataset_id: str
    plugin_id: str
    dataset_name: Optional[str]
    created_at: Optional[datetime]
    last_ingested_at: Optional[datetime]
    row_count: Optional[int]
    source_filename: Optional[str]
    is_deleted: Optional[bool] = False

# --- FastAPI app initialization ---
def create_db_and_tables():
    try:
        logger.info("Connecting to database to create tables...")
        Base.metadata.create_all(bind=engine)
        logger.info("Tables created successfully.")
        
        # Initialize plugin manager
        plugins_dir = os.path.join(os.path.dirname(__file__), "..", "..", "plugins")
        nl_to_sql.initialize_plugins(plugins_dir)
        logger.info("Plugin manager initialized.")
        
        # Compile metric views for each plugin
        if nl_to_sql.PLUGIN_MANAGER:
            for name, plugin in nl_to_sql.PLUGIN_MANAGER.plugins.items():
                try:
                    # Skip compiling metrics if the plugin's base tables don't exist yet
                    with engine.connect() as conn:
                        missing_tables = [
                            t for t in plugin.get_allowed_tables()
                            if not engine.dialect.has_table(conn, t)
                        ]
                    if missing_tables:
                        logger.info(f"Skipping metric compilation for plugin {name}; missing tables: {missing_tables}")
                        continue

                    compiled = compile_metrics(plugin)
                    plugin.compiled_views = [c.view_name for c in compiled]
                    plugin.compiled_view_sql = [c.sql for c in compiled]
                    with engine.begin() as conn:
                        for c in compiled:
                            conn.execute(text(c.sql))
                    logger.info(f"Compiled {len(compiled)} metric views for plugin {name}")
                except Exception as e:
                    logger.error(f"Failed compiling metrics for plugin {name}: {e}")

        # Set default plugin (prefer restaurant, else first available)
        default_plugin_id = "restaurant"
        if default_plugin_id not in nl_to_sql.PLUGIN_MANAGER.get_plugin_names():
            names = nl_to_sql.PLUGIN_MANAGER.get_plugin_names()
            default_plugin_id = names[0] if names else None

        if default_plugin_id and nl_to_sql.set_active_plugin(default_plugin_id):
            default_plugin = nl_to_sql.get_active_plugin()
            INSIGHT_ENGINES[default_plugin.plugin_name] = InsightEngine(default_plugin)
            logger.info(f"Insight engine initialized for default plugin '{default_plugin.plugin_name}'.")
        else:
            logger.warning("No valid plugin could be activated at startup.")
    except Exception as e:
        logger.error(f"Error initializing plugins: {e}")

app = FastAPI(on_startup=[create_db_and_tables])

# --- Dependency ---
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- Helper Functions ---
def get_last_updated(db: Session):
    last_ingestion = db.query(IngestionRun).order_by(IngestionRun.ingested_at.desc()).first()
    return last_ingestion.ingested_at.isoformat() if last_ingestion else None


def get_dataset_or_400(db: Session, dataset_id: Optional[str], plugin_id: str):
    if not dataset_id:
        raise HTTPException(status_code=400, detail="dataset_id is required")
    try:
        ds_uuid = UUID(str(dataset_id))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid dataset_id")
    ds = (
        db.query(Dataset)
        .filter(Dataset.dataset_id == ds_uuid, Dataset.is_deleted == False)  # type: ignore
        .first()
    )
    if not ds:
        raise HTTPException(status_code=404, detail="Dataset not found")
    if ds.plugin_id != plugin_id:
        raise HTTPException(status_code=400, detail="Dataset does not belong to the specified plugin")
    return ds


def ensure_active_plugin(plugin_name: Optional[str] = None):
    """Ensures a plugin is active and returns it."""
    if plugin_name:
        if not nl_to_sql.set_active_plugin(plugin_name):
            raise HTTPException(status_code=404, detail=f"Plugin '{plugin_name}' not found")
    elif not nl_to_sql.ACTIVE_PLUGIN:
        raise HTTPException(status_code=400, detail="No active plugin. Set one first.")
    return nl_to_sql.get_active_plugin()


def get_insight_engine_for_plugin(plugin_name: str) -> InsightEngine:
    """Returns cached insight engine for a plugin."""
    if plugin_name not in INSIGHT_ENGINES:
        active_plugin = ensure_active_plugin(plugin_name)
        INSIGHT_ENGINES[plugin_name] = InsightEngine(active_plugin)
    return INSIGHT_ENGINES[plugin_name]


def persist_generated_insights(db: Session, insights: List, plugin: str, dataset_id: Optional[str]):
    """Persists generated insights as a run + items."""
    run = InsightsRun(plugin=plugin, dataset_id=dataset_id)
    db.add(run)
    db.flush()  # get run_id

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


def fetch_latest_insights(db: Session, plugin: str, dataset_id: Optional[str], limit: int = 10) -> List[dict]:
    """Fetch insights from the most recent run for a plugin/dataset."""
    run_query = (
        db.query(InsightsRun)
        .filter(InsightsRun.plugin == plugin)
    )
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
    """Lightweight chat integration: respond using cached insights, never recompute."""
    q_lower = question.lower()
    if "insight" not in q_lower:
        return None

    insights = fetch_latest_insights(db, plugin, dataset_id, limit=5)

    if not insights:
        return {
            "answer_type": "insights",
            "answer": [],
            "explanation": "No cached insights available. Run /insights/run to generate them.",
            "data_last_updated": last_updated,
            "confidence": "low",
            "plugin": plugin,
        }

    filtered = insights
    if "critical" in q_lower:
        critical_only = [i for i in insights if i.get("severity") == "critical"]
        if critical_only:
            filtered = critical_only

    explanation = "Served from latest generated insights cache; no recomputation performed."
    return {
        "answer_type": "insights",
        "answer": filtered,
        "explanation": explanation,
        "data_last_updated": last_updated,
        "confidence": "medium",
        "plugin": plugin,
    }


def dataset_to_meta(ds: Dataset) -> dict:
    return {
        "dataset_id": str(ds.dataset_id),
        "plugin_id": ds.plugin_id,
        "plugin": ds.plugin_id,  # alias for frontend compatibility
        "dataset_name": ds.dataset_name,
        "created_at": ds.created_at.isoformat() if ds.created_at else None,
        "last_ingested_at": ds.last_ingested_at.isoformat() if ds.last_ingested_at else None,
        "row_count": ds.row_count,
        "source_filename": ds.source_filename,
        "filename": ds.source_filename,  # alias for frontend compatibility
        "is_deleted": ds.is_deleted,
        "version": ds.version,
    }


def build_scheduled_insight_job(plugin: str, cron: str = "0 8 * * MON") -> dict:
    """
    Stub helper to hand off to an external scheduler/worker.
    Returns the payload an orchestrator can call against /insights/run.
    """
    return {
        "plugin": plugin,
        "cron": cron,
        "endpoint": "/insights/run",
        "method": "POST",
    }

# --- API Endpoints ---
@app.post("/insights/run")
def run_insights(request: InsightRunRequest, db: Session = Depends(get_db)):
    """On-demand insight generation for the active or specified plugin."""
    t0 = time.time()
    try:
        active_plugin = ensure_active_plugin(request.plugin)
        ds = get_dataset_or_400(db, request.dataset_id, active_plugin.plugin_name)
        engine = get_insight_engine_for_plugin(active_plugin.plugin_name)
        generated = engine.run_all_insights(db, dataset_id=str(ds.dataset_id))
        if request.limit:
            generated = generated[: request.limit]

        if generated:
            run_id = persist_generated_insights(db, generated, active_plugin.plugin_name, request.dataset_id)
        else:
            run_id = None

        record_audit_log(
            db,
            plugin_id=active_plugin.plugin_name,
            dataset_id=request.dataset_id,
            user_question="insights_run",
            intent="insights_run",
            generated_sql=None,
            sql_valid=True,
            execution_ms=int((time.time() - t0) * 1000),
            rows_returned=len(generated),
            confidence="medium",
            failure_reason=None,
            model_name=None,
        )

        return {
            "plugin": active_plugin.plugin_name,
            "run_id": run_id,
            "count": len(generated),
            "insights": [engine.to_dict(i) for i in generated],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error running insights: {e}")
        record_audit_log(
            db,
            plugin_id=request.plugin,
            dataset_id=request.dataset_id,
            user_question="insights_run",
            intent="insights_run",
            generated_sql=None,
            sql_valid=False,
            execution_ms=int((time.time() - t0) * 1000),
            rows_returned=None,
            confidence="low",
            failure_reason=str(e),
            model_name=None,
        )
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/insights/latest")
def latest_insights(
    plugin: Optional[str] = Query(None),
    dataset_id: Optional[str] = Query(None),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """Return latest generated insights without recomputation."""
    try:
        active_plugin = ensure_active_plugin(plugin)
        get_dataset_or_400(db, dataset_id, active_plugin.plugin_name)
        insights = fetch_latest_insights(db, active_plugin.plugin_name, dataset_id, limit)
        return {
            "plugin": active_plugin.plugin_name,
            "count": len(insights),
            "insights": insights,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving insights: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/upload/sales")
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
        
        # Column mapping and validation
        DEFAULT_COLUMN_MAPPING = {
            'order_id': 'order_id',
            'order_datetime': 'order_datetime',
            'item_name': 'item_name',
            'category': 'category',
            'quantity': 'quantity',
            'item_price': 'item_price',
            'total_line_amount': 'total_line_amount',
            'payment_type': 'payment_type',
            'discount_amount': 'discount_amount',
            'tax_amount': 'tax_amount',
        }
        REQUIRED_COLUMNS = ['order_id', 'order_datetime', 'item_name', 'quantity', 'item_price', 'total_line_amount']
        
        df.rename(columns=DEFAULT_COLUMN_MAPPING, inplace=True)
        
        missing_columns = [col for col in REQUIRED_COLUMNS if col not in df.columns]
        if missing_columns:
            raise HTTPException(status_code=400, detail=f"Missing required columns: {', '.join(missing_columns)}")

        df['order_datetime'] = pd.to_datetime(df['order_datetime'])
        df['dataset_id'] = dataset_uuid
        # Generate primary keys because pandas.to_sql won't use client-side defaults
        df['id'] = [uuid4() for _ in range(len(df))]
        
        # Append; keep historical datasets isolated via dataset_id
        df.to_sql(SalesTransaction.__tablename__, engine, if_exists='append', index=False)
        existing = db.query(Dataset).filter(Dataset.dataset_id == dataset_uuid).first()
        now_ts = datetime.utcnow()
        if existing:
            dataset_obj = existing
            dataset_obj.plugin_id = plugin_id
        else:
            dataset_obj = Dataset(
                dataset_id=dataset_uuid,
                plugin_id=plugin_id,
                dataset_name=os.path.splitext(file.filename)[0],
                created_at=now_ts,
            )
        dataset_obj.last_ingested_at = now_ts
        dataset_obj.row_count = len(df)
        dataset_obj.source_filename = file.filename
        dataset_obj.is_deleted = False
        dataset_obj.version = (dataset_obj.version or 1) + 1
        dataset_obj = db.merge(dataset_obj)
        
        ingestion_record = IngestionRun(
            dataset_name="sales",
            filename=file.filename,
            row_count=len(df),
            plugin_id=plugin_id,
            dataset_id=dataset_obj.dataset_id,
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


@app.get("/datasets")
def list_datasets_endpoint(plugin_id: Optional[str] = Query(None), db: Session = Depends(get_db)):
    query = db.query(Dataset).filter(Dataset.is_deleted == False)  # type: ignore
    if plugin_id:
        query = query.filter(Dataset.plugin_id == plugin_id)
    datasets = query.order_by(Dataset.created_at.desc()).all()
    return [dataset_to_meta(ds) for ds in datasets]


@app.get("/datasets/{dataset_id}")
def get_dataset(dataset_id: str, db: Session = Depends(get_db)):
    try:
        ds_uuid = UUID(str(dataset_id))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid dataset_id")
    ds = db.query(Dataset).filter(Dataset.dataset_id == ds_uuid, Dataset.is_deleted == False).first()  # type: ignore
    if not ds:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return dataset_to_meta(ds)


@app.delete("/datasets/{dataset_id}")
def soft_delete_dataset(dataset_id: str, db: Session = Depends(get_db)):
    try:
        ds_uuid = UUID(str(dataset_id))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid dataset_id")
    ds = db.query(Dataset).filter(Dataset.dataset_id == ds_uuid).first()
    if not ds:
        raise HTTPException(status_code=404, detail="Dataset not found")
    ds.is_deleted = True
    db.add(ds)
    db.commit()
    return {"status": "deleted", "dataset_id": dataset_id}

# --- Jobs helpers ---
UPLOAD_ROOT = Path("/tmp/uploads")
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)


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

# --- Job endpoints ---
@app.get("/jobs/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.job_id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id": str(job.job_id),
        "job_type": job.job_type,
        "plugin_id": job.plugin_id,
        "dataset_id": str(job.dataset_id) if job.dataset_id else None,
        "status": job.status,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "progress_pct": job.progress_pct,
        "result": job.result,
        "failure_reason": job.failure_reason,
    }


@app.get("/jobs")
def list_jobs(plugin_id: Optional[str] = None, status: Optional[str] = None, limit: int = 50, db: Session = Depends(get_db)):
    q = db.query(Job)
    if plugin_id:
        q = q.filter(Job.plugin_id == plugin_id)
    if status:
        q = q.filter(Job.status == status)
    jobs = q.order_by(Job.created_at.desc()).limit(limit).all()
    return [
        {
            "job_id": str(j.job_id),
            "job_type": j.job_type,
            "status": j.status,
            "plugin_id": j.plugin_id,
            "dataset_id": str(j.dataset_id) if j.dataset_id else None,
            "created_at": j.created_at,
            "result": j.result,
            "failure_reason": j.failure_reason,
        }
        for j in jobs
    ]


@app.post("/chat")
def chat(chat_query: ChatQuery, db: Session = Depends(get_db)):
    last_updated = get_last_updated(db)
    t0 = time.time()
    generated_sql = None
    
    try:
        # Switch plugin if specified
        active_plugin = ensure_active_plugin(chat_query.plugin)
        dataset_id = chat_query.dataset_id
        ds = get_dataset_or_400(db, dataset_id, active_plugin.plugin_name)
        dataset_version = ds.version
        
        # First, try to satisfy insight-focused questions from cached insights
        cached_response = maybe_answer_with_cached_insights(chat_query.query, active_plugin.plugin_name, dataset_id, db, last_updated)
        if cached_response:
            return cached_response

        # Generate SQL with multi-step guardrails
        generation = nl_to_sql.generate_sql(chat_query.query, dataset_id=str(ds.dataset_id), dataset_version=dataset_version)
        generated_sql = generation.sql

        if generation.intent != "analytics_query" or not generated_sql:
            record_audit_log(
                db,
                plugin_id=active_plugin.plugin_name,
                dataset_id=dataset_id,
                user_question=chat_query.query,
                intent=generation.intent,
                generated_sql=None,
                sql_valid=False,
                execution_ms=int((time.time() - t0) * 1000),
                rows_returned=None,
                confidence=generation.confidence,
                failure_reason=generation.failure_reason or "unsupported_intent",
                model_name=generation.model_name,
            )
            return {
                "answer_type": "text",
                "answer": "I need more context to answer that. Please ask a data question related to the plugin.",
                "explanation": generation.failure_reason or "Question not supported.",
                "sql": None,
                "data_last_updated": last_updated,
                "confidence": generation.confidence,
                "plugin": active_plugin.plugin_name,
                "assumptions": generation.assumptions,
            }

        # Enforce dataset filter and execute with parameter
        scoped_sql = nl_to_sql.SQL_GUARD.enforce_dataset_filter(generated_sql, "dataset_id")
        # Fix date literal interval syntax if present
        import re
        scoped_sql = re.sub(
            r"DATE\('(\d{4}-\d{2}-\d{2})'\s*-\s*INTERVAL\s*'(\d+\s+day[s]?)'\)",
            r"(DATE '\1' - INTERVAL '\2')",
            scoped_sql,
            flags=re.IGNORECASE,
        )
        conn = db.connection()
        conn.execute(text("SET statement_timeout = '5s';")) # 5 second timeout
        # DB cache
        from cache.cache import stable_hash, cache_get, cache_set, DB_RESULT_CACHE_TTL_SECONDS
        params = {"dataset_id": ds.dataset_id}
        hash_params = {"dataset_id": str(ds.dataset_id)}
        sql_norm = scoped_sql.strip().rstrip(";")
        db_key = stable_hash({"ds": str(ds.dataset_id), "v": dataset_version, "sql": sql_norm, "params": hash_params})
        db_cache_hit = False
        cached = cache_get("db_result", db_key)
        def _serialize_val(v):
            from uuid import UUID
            return str(v) if isinstance(v, UUID) else v

        def _serialize_payload(payload):
            if payload.get("type") == "scalar":
                return {
                    "type": "scalar",
                    "value": _serialize_val(payload.get("value")),
                    "row_count": payload.get("row_count", 1),
                }
            if payload.get("type") == "table":
                rows = payload.get("rows", [])
                return {
                    "type": "table",
                    "rows": [{k: _serialize_val(v) for k, v in dict(r).items()} for r in rows],
                    "row_count": payload.get("row_count", len(rows)),
                }
            return payload

        if cached is not None:
            db_cache_hit = True
            result_payload = _serialize_payload(cached)
        else:
            rows = conn.execute(text(sql_norm), params).fetchall()
            if len(rows) == 1 and len(rows[0]) == 1:
                result_payload = {"type": "scalar", "value": _serialize_val(rows[0][0]), "row_count": 1}
            else:
                result_payload = {
                    "type": "table",
                    "rows": [{k: _serialize_val(v) for k, v in dict(r).items()} for r in rows],
                    "row_count": len(rows),
                }
            cache_set("db_result", db_key, _serialize_payload(result_payload), DB_RESULT_CACHE_TTL_SECONDS)
        
        # Determine answer type
        answer_type = generation.answer_type or ("number" if result_payload["type"] == "scalar" else "table")
        if result_payload["type"] == "scalar":
            val = result_payload["value"]
            # normalize None to 0 for numeric aggregates
            if val is None:
                val = 0
            answer = val
        else:
            answer = result_payload["rows"]

        exec_ms = int((time.time() - t0) * 1000)
        record_audit_log(
            db,
            plugin_id=active_plugin.plugin_name,
            dataset_id=dataset_id,
            user_question=chat_query.query,
            intent=generation.intent,
            generated_sql=scoped_sql,
            sql_valid=True,
            execution_ms=exec_ms,
            rows_returned=result_payload["row_count"],
            confidence=generation.confidence,
            failure_reason=None,
            model_name=generation.model_name,
        )
        logger.info(json.dumps({
            "event": "chat_query",
            "plugin_id": active_plugin.plugin_name,
            "dataset_id": str(dataset_id),
            "sql": scoped_sql,
            "rows": result_payload["row_count"],
            "ms": exec_ms,
        }))
        
        return {
            "answer_type": answer_type,
            "answer": answer,
            "explanation": "Validated SQL executed against dataset.",
            "sql": scoped_sql,
            "data_last_updated": last_updated,
            "confidence": generation.confidence,
            "plugin": active_plugin.plugin_name,
            "assumptions": generation.assumptions,
            "dataset_filter_enforced": True,
            "cache": {
                "llm_sql": {"hit": generation.cache_info.get("llm_cache_hit", False), "key": generation.cache_info.get("llm_cache_key")},
                "db_result": {"hit": db_cache_hit, "key": db_key[:8]},
            },
        }

    except HTTPException:
        raise
    except ValueError as e:
        record_audit_log(
            db,
            plugin_id=chat_query.plugin,
            dataset_id=chat_query.dataset_id,
            user_question=chat_query.query,
            intent="analytics_query",
            generated_sql=generated_sql,
            sql_valid=False,
            execution_ms=int((time.time() - t0) * 1000),
            rows_returned=None,
            confidence="low",
            failure_reason=str(e),
            model_name=None,
        )
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error during chat processing: {e}")
        record_audit_log(
            db,
            plugin_id=chat_query.plugin,
            dataset_id=chat_query.dataset_id,
            user_question=chat_query.query,
            intent="analytics_query",
            generated_sql=generated_sql,
            sql_valid=False,
            execution_ms=int((time.time() - t0) * 1000),
            rows_returned=None,
            confidence="low",
            failure_reason=str(e),
            model_name=None,
        )
        return {"answer": "I'm sorry, but I encountered an error trying to answer your question.", "confidence": "low", "sql": generated_sql, "explanation": str(e), "plugin": None, "dataset_filter_enforced": True}

@app.post("/plugin/switch")
def switch_plugin(request: PluginSwitchRequest):
    """Switch to a different plugin."""
    try:
        if nl_to_sql.set_active_plugin(request.plugin):
            active_plugin = nl_to_sql.get_active_plugin()
            return {
                "status": "success",
                "plugin": active_plugin.plugin_name,
                "tables": list(active_plugin.get_allowed_tables()),
                "metrics": list(active_plugin.metrics.keys())
            }
        else:
            raise HTTPException(status_code=404, detail=f"Plugin '{request.plugin}' not found")
    except Exception as e:
        logger.error(f"Error switching plugin: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/plugins")
def list_plugins():
    """List all available plugins."""
    try:
        summaries = nl_to_sql.PLUGIN_MANAGER.list_summaries() if nl_to_sql.PLUGIN_MANAGER else []
        active_plugin = nl_to_sql.ACTIVE_PLUGIN.plugin_name if nl_to_sql.ACTIVE_PLUGIN else None
        return {"plugins": summaries, "active_plugin": active_plugin}
    except Exception as e:
        logger.error(f"Error listing plugins: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/plugins/{plugin_id}")
def get_plugin_detail(plugin_id: str):
    try:
        plugin = nl_to_sql.PLUGIN_MANAGER.get_plugin(plugin_id) if nl_to_sql.PLUGIN_MANAGER else None
        if not plugin:
            raise HTTPException(status_code=404, detail="Plugin not found")
        definition = plugin.to_definition()
        return {
            "id": definition.id,
            "name": definition.name,
            "description": definition.description,
            "domains": definition.domains,
            "required_columns": definition.required_columns,
            "sample_csvs": definition.sample_csvs,
            "tables": list(definition.tables.keys()),
            "primary_time_column": definition.primary_time_column,
            "metrics": list(definition.metrics.keys()),
            "question_packs": list(definition.question_packs.keys()),
            "policy": definition.policy.__dict__ if definition.policy else {},
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting plugin detail: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/plugins/{plugin_id}/views")
def get_plugin_views(plugin_id: str):
    try:
        plugin = nl_to_sql.PLUGIN_MANAGER.get_plugin(plugin_id) if nl_to_sql.PLUGIN_MANAGER else None
        if not plugin:
            raise HTTPException(status_code=404, detail="Plugin not found")
        return {"plugin": plugin_id, "views": getattr(plugin, "compiled_views", [])}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting plugin views: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/plugins/{plugin_id}/questions")
def get_plugin_questions(plugin_id: str):
    try:
        plugin = nl_to_sql.PLUGIN_MANAGER.get_plugin(plugin_id) if nl_to_sql.PLUGIN_MANAGER else None
        if not plugin:
            raise HTTPException(status_code=404, detail="Plugin not found")
        packs = []
        for pack_name, pack in plugin.question_packs.items():
            packs.append(
                {
                    "id": pack_name,
                    "title": pack.description or pack_name,
                    "questions": [p.pattern for p in pack.patterns],
                }
            )
        return packs
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting plugin questions: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/plugin/info")
def get_plugin_info():
    """Get information about the active plugin."""
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
                "enable_predictions": active_plugin.policy.enable_predictions
            }
        }
    except Exception as e:
        logger.error(f"Error getting plugin info: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
def read_root():
    return {"message": "Restaurant Data Analyst Chat API is running."}

@app.get("/health")
def health_check(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        plugin_count = len(nl_to_sql.PLUGIN_MANAGER.plugins) if nl_to_sql.PLUGIN_MANAGER else 0
        return {"status": "ok", "database_connection": "successful", "plugins_loaded": plugin_count}
    except Exception as e:
        return {"status": "error", "database_connection": "failed", "error": str(e)}
