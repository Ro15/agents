"""
Extended models for new features:
- Multi-turn conversations
- Query history & favorites
- Feedback & corrections
- Custom dashboards
- Scheduled reports
- Data connectors
- Column profiles / data catalog
- Rate limiting & LLM cost tracking
"""

from uuid import uuid4
from sqlalchemy import Column, text, ForeignKey, Boolean
from sqlalchemy.types import Integer, String, TIMESTAMP, NUMERIC, UUID as UUID_TYPE, Text
from sqlalchemy import JSON as JSON_TYPE

from app.database import Base


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
    role = Column(String, nullable=False)  # "user" | "assistant"
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
    query_history_id = Column(UUID_TYPE(as_uuid=True), nullable=True, index=True)
    plugin_id = Column(String, index=True)
    question = Column(Text)
    original_sql = Column(Text, nullable=True)
    corrected_sql = Column(Text, nullable=True)
    rating = Column(Integer, nullable=False)  # 1 = thumbs-up, -1 = thumbs-down
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
    widget_type = Column(String, nullable=False)  # "chart" | "kpi" | "table"
    query_text = Column(Text, nullable=True)
    sql = Column(Text, nullable=True)
    chart_hint = Column(String, nullable=True)
    config = Column(JSON_TYPE, nullable=True)
    position = Column(JSON_TYPE, nullable=True)  # {x, y, w, h}
    created_at = Column(TIMESTAMP, server_default=text("now()"))


# ── Scheduled reports & alerts ──────────────────────────────────────────

class ScheduledReport(Base):
    __tablename__ = "scheduled_reports"
    report_id = Column(UUID_TYPE(as_uuid=True), primary_key=True, default=uuid4)
    title = Column(String, nullable=False)
    plugin_id = Column(String, index=True)
    dataset_id = Column(String, nullable=True)
    schedule_cron = Column(String, nullable=False)
    report_type = Column(String, nullable=False)  # "insights" | "query" | "dashboard"
    config = Column(JSON_TYPE, nullable=True)
    delivery = Column(JSON_TYPE, nullable=True)  # {method, target}
    enabled = Column(Boolean, server_default=text("true"))
    last_run_at = Column(TIMESTAMP, nullable=True)
    next_run_at = Column(TIMESTAMP, nullable=True)
    created_at = Column(TIMESTAMP, server_default=text("now()"))


# ── Data connectors ─────────────────────────────────────────────────────

class DataConnector(Base):
    __tablename__ = "data_connectors"
    connector_id = Column(UUID_TYPE(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String, nullable=False)
    connector_type = Column(String, nullable=False)  # postgresql, mysql, mssql, bigquery, snowflake, excel, sheets, api
    config = Column(JSON_TYPE, nullable=True)
    plugin_id = Column(String, nullable=True, index=True)
    status = Column(String, server_default=text("'configured'"))
    last_sync_at = Column(TIMESTAMP, nullable=True)
    created_at = Column(TIMESTAMP, server_default=text("now()"))


# ── Data catalog / column profiles ──────────────────────────────────────

class ColumnProfile(Base):
    __tablename__ = "column_profiles"
    id = Column(UUID_TYPE(as_uuid=True), primary_key=True, default=uuid4)
    dataset_id = Column(UUID_TYPE(as_uuid=True), index=True, nullable=False)
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


# ── Rate-limiting & LLM cost tracking ───────────────────────────────────

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
