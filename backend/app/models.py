"""
All SQLAlchemy models in a single module.
Imported by routes and helpers; avoids circular dependencies.
"""

from uuid import uuid4
from sqlalchemy import Column, text, ForeignKey, Boolean, Index
from sqlalchemy import JSON as JSON_TYPE
from sqlalchemy.types import Integer, String, TIMESTAMP, NUMERIC, UUID as UUID_TYPE, Text

from app.database import Base


# ── Core domain models ──────────────────────────────────────────────────

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
    payload = Column(JSON_TYPE)


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


# ── Indexes ─────────────────────────────────────────────────────────────

Index("idx_sales_transactions_dataset_time", SalesTransaction.dataset_id, SalesTransaction.order_datetime)
Index("idx_sales_transactions_dataset_item", SalesTransaction.dataset_id, SalesTransaction.item_name)


# ── Multi-turn conversations ────────────────────────────────────────────

class ConversationThread(Base):
    __tablename__ = "conversation_threads"
    thread_id = Column(UUID_TYPE(as_uuid=True), primary_key=True, default=uuid4)
    plugin_id = Column(String, index=True)
    dataset_id = Column(String, nullable=True, index=True)
    title = Column(String, nullable=True)
    created_at = Column(TIMESTAMP, server_default=text("now()"))
    updated_at = Column(TIMESTAMP, server_default=text("now()"))


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"
    message_id = Column(UUID_TYPE(as_uuid=True), primary_key=True, default=uuid4)
    thread_id = Column(UUID_TYPE(as_uuid=True), ForeignKey("conversation_threads.thread_id", ondelete="CASCADE"), index=True)
    role = Column(String, nullable=False)
    content = Column(Text)
    sql = Column(Text, nullable=True)
    answer_type = Column(String, nullable=True)
    created_at = Column(TIMESTAMP, server_default=text("now()"))


# ── Query history & favorites ───────────────────────────────────────────

class QueryHistoryEntry(Base):
    __tablename__ = "query_history"
    id = Column(UUID_TYPE(as_uuid=True), primary_key=True, default=uuid4)
    plugin_id = Column(String, index=True)
    dataset_id = Column(String, nullable=True, index=True)
    question = Column(Text, nullable=False)
    sql = Column(Text, nullable=True)
    answer_type = Column(String, nullable=True)
    answer_summary = Column(Text, nullable=True)
    confidence = Column(String, nullable=True)
    is_favorite = Column(Boolean, server_default=text("false"))
    share_token = Column(String, nullable=True, unique=True, index=True)
    created_at = Column(TIMESTAMP, server_default=text("now()"))


# ── Feedback & query correction ─────────────────────────────────────────

class QueryFeedback(Base):
    __tablename__ = "query_feedback"
    id = Column(UUID_TYPE(as_uuid=True), primary_key=True, default=uuid4)
    query_history_id = Column(UUID_TYPE(as_uuid=True), ForeignKey("query_history.id", ondelete="SET NULL"), nullable=True, index=True)
    plugin_id = Column(String, index=True)
    question = Column(Text)
    original_sql = Column(Text, nullable=True)
    corrected_sql = Column(Text, nullable=True)
    rating = Column(Integer, nullable=False)
    comment = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP, server_default=text("now()"))


# ── Custom dashboards ──────────────────────────────────────────────────

class CustomDashboard(Base):
    __tablename__ = "custom_dashboards"
    dashboard_id = Column(UUID_TYPE(as_uuid=True), primary_key=True, default=uuid4)
    title = Column(String, nullable=False)
    plugin_id = Column(String, index=True)
    description = Column(Text, nullable=True)
    layout = Column(JSON_TYPE, nullable=True)
    created_at = Column(TIMESTAMP, server_default=text("now()"))
    updated_at = Column(TIMESTAMP, server_default=text("now()"))
    is_deleted = Column(Boolean, server_default=text("false"))


class DashboardWidget(Base):
    __tablename__ = "dashboard_widgets"
    widget_id = Column(UUID_TYPE(as_uuid=True), primary_key=True, default=uuid4)
    dashboard_id = Column(UUID_TYPE(as_uuid=True), ForeignKey("custom_dashboards.dashboard_id", ondelete="CASCADE"), index=True)
    title = Column(String, nullable=False)
    widget_type = Column(String, nullable=False)
    query_text = Column(Text, nullable=True)
    sql = Column(Text, nullable=True)
    chart_hint = Column(String, nullable=True)
    config = Column(JSON_TYPE, nullable=True)
    position = Column(JSON_TYPE, nullable=True)
    created_at = Column(TIMESTAMP, server_default=text("now()"))


# ── Scheduled reports ───────────────────────────────────────────────────

class ScheduledReport(Base):
    __tablename__ = "scheduled_reports"
    report_id = Column(UUID_TYPE(as_uuid=True), primary_key=True, default=uuid4)
    title = Column(String, nullable=False)
    plugin_id = Column(String, index=True)
    dataset_id = Column(String, nullable=True)
    schedule_cron = Column(String, nullable=False)
    report_type = Column(String, nullable=False)
    config = Column(JSON_TYPE, nullable=True)
    delivery = Column(JSON_TYPE, nullable=True)
    enabled = Column(Boolean, server_default=text("true"))
    last_run_at = Column(TIMESTAMP, nullable=True)
    next_run_at = Column(TIMESTAMP, nullable=True)
    created_at = Column(TIMESTAMP, server_default=text("now()"))


# ── Data connectors ─────────────────────────────────────────────────────

class DataConnector(Base):
    __tablename__ = "data_connectors"
    connector_id = Column(UUID_TYPE(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String, nullable=False)
    connector_type = Column(String, nullable=False)
    config = Column(JSON_TYPE, nullable=True)
    plugin_id = Column(String, nullable=True, index=True)
    status = Column(String, server_default=text("'configured'"))
    last_sync_at = Column(TIMESTAMP, nullable=True)
    created_at = Column(TIMESTAMP, server_default=text("now()"))


# ── Data catalog ────────────────────────────────────────────────────────

class ColumnProfile(Base):
    __tablename__ = "column_profiles"
    id = Column(UUID_TYPE(as_uuid=True), primary_key=True, default=uuid4)
    dataset_id = Column(UUID_TYPE(as_uuid=True), ForeignKey("datasets.dataset_id", ondelete="CASCADE"), index=True, nullable=False)
    column_name = Column(String, nullable=False)
    data_type = Column(String, nullable=True)
    null_count = Column(Integer, nullable=True)
    distinct_count = Column(Integer, nullable=True)
    min_value = Column(String, nullable=True)
    max_value = Column(String, nullable=True)
    mean_value = Column(NUMERIC, nullable=True)
    description = Column(Text, nullable=True)
    sample_values = Column(JSON_TYPE, nullable=True)
    profiled_at = Column(TIMESTAMP, server_default=text("now()"))


# ── Rate limiting & LLM cost tracking ───────────────────────────────────

class RateLimitLog(Base):
    __tablename__ = "rate_limit_log"
    id = Column(UUID_TYPE(as_uuid=True), primary_key=True, default=uuid4)
    client_ip = Column(String, index=True, nullable=False)
    endpoint = Column(String, nullable=False)
    created_at = Column(TIMESTAMP, server_default=text("now()"))


class LLMCostLog(Base):
    __tablename__ = "llm_cost_log"
    id = Column(UUID_TYPE(as_uuid=True), primary_key=True, default=uuid4)
    plugin_id = Column(String, nullable=True)
    model_name = Column(String, nullable=True)
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    estimated_cost = Column(NUMERIC, nullable=True)
    endpoint = Column(String, nullable=True)
    created_at = Column(TIMESTAMP, server_default=text("now()"))
