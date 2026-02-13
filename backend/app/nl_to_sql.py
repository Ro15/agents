"""
Natural Language to SQL conversion module.

This module orchestrates the conversion of natural language questions to SQL queries
using an LLM with plugin-based configuration for sector-agnostic operation.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List
from sqlalchemy import inspect
from app.llm_service import generate_sql_with_llm, SchemaContext, LLMConfig, LLMResponse
from app.sql_guard import SQLGuard, SQLGuardError
from app.plugin_loader import PluginConfig, PluginManager

logger = logging.getLogger(__name__)

# Plugin manager instance
PLUGIN_MANAGER = None
ACTIVE_PLUGIN = None
SQL_GUARD = None


def classify_intent(question: str) -> str:
    """Cheap intent classifier to avoid another model call."""
    q = (question or "").lower()
    if not q.strip():
        return "needs_clarification"
    unsupported_keywords = ["joke", "who are you", "lyrics", "story", "explain plugin", "weather"]
    if any(k in q for k in unsupported_keywords):
        return "unsupported"
    # If no verb-like tokens, ask for clarification
    if len(q.split()) < 3:
        return "needs_clarification"
    return "analytics_query"


def normalize_sql(sql: str, default_limit: int = 200) -> str:
    cleaned = sql.strip().rstrip(";")
    if "limit" not in cleaned.lower():
        cleaned += f" LIMIT {default_limit}"
    return cleaned


def fix_date_literal_intervals(sql: str) -> str:
    """
    Fixes patterns like DATE('YYYY-MM-DD' - INTERVAL '1 day') which Postgres rejects.
    Rewrites to (DATE 'YYYY-MM-DD' - INTERVAL '1 day').
    """
    import re
    pattern = r"DATE\('(\d{4}-\d{2}-\d{2})'\s*-\s*INTERVAL\s*'(\d+\s+day[s]?)'\)"
    return re.sub(pattern, r"(DATE '\1' - INTERVAL '\2')", sql, flags=re.IGNORECASE)


def clamp_date_range(sql: str, time_column: Optional[str], max_days: Optional[int]) -> str:
    """If a max range is configured and the query doesn't mention the time column, add a clamp."""
    if not time_column or not max_days:
        return sql
    if time_column.lower() in sql.lower():
        return sql
    lower_sql = sql.lower()
    limit_idx = lower_sql.rfind("limit")
    clamp_clause = f"{time_column} >= CURRENT_DATE - INTERVAL '{max_days} days'"
    if limit_idx != -1:
        before = sql[:limit_idx].rstrip()
        after = sql[limit_idx:]
        if "where" in before.lower():
            return f"{before} AND {clamp_clause} {after}"
        return f"{before} WHERE {clamp_clause} {after}"
    if "where" in lower_sql:
        return f"{sql} AND {clamp_clause}"
    return f"{sql} WHERE {clamp_clause}"


@dataclass
class SQLGenerationResult:
    sql: Optional[str]
    answer_type: str
    assumptions: List[str]
    confidence: str
    intent: str
    repairs: int
    model_name: Optional[str] = None
    failure_reason: Optional[str] = None
    cache_info: dict = None
    chart_hint: str = "none"
    summary: str = ""

    def __post_init__(self):
        if self.cache_info is None:
            self.cache_info = {}


def initialize_plugins(plugins_dir: str = "plugins"):
    """
    Initializes the plugin manager.
    Must be called at application startup.
    
    Args:
        plugins_dir: Base directory containing plugin configurations
    """
    global PLUGIN_MANAGER
    
    PLUGIN_MANAGER = PluginManager(plugins_dir)
    logger.info(f"Plugin manager initialized with {len(PLUGIN_MANAGER.plugins)} plugins")
    logger.info(f"Available plugins: {PLUGIN_MANAGER.get_plugin_names()}")


def set_active_plugin(plugin_name: str) -> bool:
    """
    Sets the active plugin for SQL generation.
    
    Args:
        plugin_name: Name of the plugin to activate
    
    Returns:
        True if successful, False otherwise
    """
    global ACTIVE_PLUGIN, SQL_GUARD
    
    if not PLUGIN_MANAGER:
        raise ValueError("Plugin manager not initialized. Call initialize_plugins() first.")
    
    if not PLUGIN_MANAGER.set_active_plugin(plugin_name):
        return False
    
    ACTIVE_PLUGIN = PLUGIN_MANAGER.get_active_plugin()
    
    # Initialize SQL guard with plugin's allowed tables and columns
    allowed_tables = {t.lower() for t in ACTIVE_PLUGIN.get_allowed_tables()}
    if getattr(ACTIVE_PLUGIN, "compiled_views", None):
        allowed_tables |= {v.lower() for v in ACTIVE_PLUGIN.compiled_views}

    allowed_columns = {c.lower() for c in ACTIVE_PLUGIN.get_allowed_columns()} | {"dataset_id"}

    # Include identifiers from compiled metric views so guard allows them
    extra_cols = set()
    if getattr(ACTIVE_PLUGIN, "compiled_view_sql", None):
        import re
        keywords = SQLGuard.ALLOWED_KEYWORDS | SQLGuard.FORBIDDEN_KEYWORDS | SQLGuard.ALLOWED_FUNCTIONS
        for sql in ACTIVE_PLUGIN.compiled_view_sql:
            ids = set(re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]*\b', sql.lower()))
            ids -= {kw.lower() for kw in keywords}
            extra_cols |= ids
    allowed_columns |= extra_cols
    SQL_GUARD = SQLGuard(allowed_tables, allowed_columns)
    
    logger.info(f"Active plugin set to: {plugin_name}")
    return True


def get_active_plugin() -> PluginConfig:
    """Gets the currently active plugin."""
    if not ACTIVE_PLUGIN:
        raise ValueError("No active plugin. Call set_active_plugin() first.")
    return ACTIVE_PLUGIN


from cache.cache import cache_get, cache_set, stable_hash, normalize_question, LLM_SQL_CACHE_TTL_SECONDS


def generate_sql(query: str, dataset_id: str = "", dataset_version: int = 0, plugin_config_hash: str = "", prompt_version: str = "v2", conversation_history: list = None) -> SQLGenerationResult:
    """
    Generates SQL from a natural language query using LLM with plugin configuration.
    Implements a two-pass repair loop and validation via SQLGuard.
    """
    if not ACTIVE_PLUGIN:
        raise ValueError("No active plugin. Call set_active_plugin() first.")

    intent = classify_intent(query)
    if intent == "unsupported":
        return SQLGenerationResult(
            sql=None,
            answer_type="text",
            assumptions=[],
            confidence="low",
            intent=intent,
            repairs=0,
            failure_reason="unsupported_intent",
        )
    if intent == "needs_clarification":
        return SQLGenerationResult(
            sql=None,
            answer_type="text",
            assumptions=[],
            confidence="low",
            intent=intent,
            repairs=0,
            failure_reason="clarification_required",
        )

    # Validate question against plugin policy
    is_valid, reason = ACTIVE_PLUGIN.validate_question(query)
    if not is_valid:
        raise ValueError(f"Question validation failed: {reason}")

    schema_context = SchemaContext(
        ACTIVE_PLUGIN.schema,
        ACTIVE_PLUGIN.get_allowed_tables(),
        ACTIVE_PLUGIN.get_allowed_columns(),
        plugin_name=ACTIVE_PLUGIN.plugin_name,
        metrics_description=ACTIVE_PLUGIN.get_metrics_description(),
        views=getattr(ACTIVE_PLUGIN, "compiled_views", []),
    )

    config = LLMConfig()
    today_iso = datetime.utcnow().date().isoformat()

    cache_info = {"llm_cache_hit": False, "llm_cache_key": None}
    key_obj = {
        "plugin": ACTIVE_PLUGIN.plugin_name,
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "question": normalize_question(query),
        "config_hash": plugin_config_hash or ACTIVE_PLUGIN.plugin_name,
        "prompt_version": prompt_version,
        "model": config.model,
    }
    cache_key = stable_hash(key_obj)
    cached = cache_get("llm_sql", cache_key)
    if cached:
        cache_info["llm_cache_hit"] = True
        cache_info["llm_cache_key"] = cache_key[:8]
        return SQLGenerationResult(
            sql=cached["sql"],
            answer_type=cached["answer_type"],
            assumptions=cached.get("assumptions", []),
            confidence="high",
            intent="analytics_query",
            repairs=0,
            model_name=cached.get("model_name"),
            failure_reason=None,
            cache_info=cache_info,
            chart_hint=cached.get("chart_hint", "none"),
            summary=cached.get("summary", ""),
        )

    attempts = 0
    last_error = None
    response: Optional[LLMResponse] = None
    sql: Optional[str] = None
    while attempts < 2:
        attempts += 1
        response = generate_sql_with_llm(
            question=query,
            schema_context=schema_context,
            config=config,
            feedback=last_error,
            timezone="Asia/Kolkata",
            today_iso=today_iso,
            conversation_history=conversation_history,
        )
        if not response:
            last_error = {"error": "llm_unavailable", "allowed_tables": list(ACTIVE_PLUGIN.get_allowed_tables()), "allowed_columns": list(ACTIVE_PLUGIN.get_allowed_columns())}
            continue

        candidate_sql = normalize_sql(
            clamp_date_range(
                fix_date_literal_intervals(response.sql),
                ACTIVE_PLUGIN.primary_time_column(),
                ACTIVE_PLUGIN.policy.max_date_range_days if ACTIVE_PLUGIN.policy else None,
            )
        )

        try:
            SQL_GUARD.validate(candidate_sql)
            sql = candidate_sql
            break
        except SQLGuardError as e:
            last_error = {
                "error": str(e),
                "allowed_tables": list(ACTIVE_PLUGIN.get_allowed_tables()),
                "allowed_columns": list(ACTIVE_PLUGIN.get_allowed_columns()),
                "time_column": ACTIVE_PLUGIN.primary_time_column(),
            }
            logger.warning(f"SQL validation failed on attempt {attempts}: {e}")
            continue

    confidence = "high" if sql and attempts == 1 else "medium" if sql else "low"

    result = SQLGenerationResult(
        sql=sql,
        answer_type=response.answer_type if response else "text",
        assumptions=response.assumptions if response else [],
        confidence=confidence if sql else "low",
        intent=intent,
        repairs=attempts - 1,
        model_name=response.model_name if response else None,
        failure_reason=None if sql else (last_error.get("error") if last_error else "generation_failed"),
        chart_hint=response.chart_hint if response else "none",
        summary=response.summary if response else "",
    )
    result.cache_info = cache_info
    if sql:
        cache_set(
            "llm_sql",
            cache_key,
            {
                "sql": sql,
                "answer_type": result.answer_type,
                "assumptions": result.assumptions,
                "model_name": result.model_name,
                "chart_hint": result.chart_hint,
                "summary": result.summary,
            },
            LLM_SQL_CACHE_TTL_SECONDS,
        )
    return result
