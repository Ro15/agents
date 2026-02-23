"""
Prompt Self-Optimization — Task 4.2
Learns from user corrections → generates prompt rules → injects into LLM context.
After 5 corrections of the same type, auto-generates a prompt rule.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

_RULE_TRIGGER_COUNT = 5    # corrections before generating a prompt rule
_MAX_RULES_PER_PLUGIN = 20


# ── Diff type classification ─────────────────────────────────────────────

DIFF_PATTERNS = {
    "wrong_column": [
        (r"no column named", "wrong_column"),
        (r"column .* does not exist", "wrong_column"),
        (r"column not found", "wrong_column"),
    ],
    "wrong_aggregation": [
        (r"sum.*instead.*count", "wrong_aggregation"),
        (r"avg.*instead", "wrong_aggregation"),
        (r"should be (sum|count|avg|max|min)", "wrong_aggregation"),
    ],
    "wrong_date": [
        (r"date.*wrong", "wrong_date"),
        (r"interval.*incorrect", "wrong_date"),
        (r"last (week|month|year)", "wrong_date"),
        (r"date_trunc", "wrong_date"),
    ],
    "missing_filter": [
        (r"add.*where", "missing_filter"),
        (r"filter.*missing", "missing_filter"),
        (r"should include.*filter", "missing_filter"),
    ],
    "wrong_join": [
        (r"join.*wrong", "wrong_join"),
        (r"should join", "wrong_join"),
        (r"missing join", "wrong_join"),
    ],
    "wrong_groupby": [
        (r"group by", "wrong_groupby"),
        (r"should group", "wrong_groupby"),
    ],
}


def classify_correction_type(original_sql: str, corrected_sql: str, comment: str = "") -> str:
    """Classify what kind of correction was made."""
    text = (f"{original_sql} {corrected_sql} {comment}").lower()
    for diff_type, patterns in DIFF_PATTERNS.items():
        for pattern, dtype in patterns:
            if re.search(pattern, text):
                return dtype
    # Structural diff
    orig_cols = set(re.findall(r"\b[a-z_][a-z0-9_]*\b", original_sql.lower()))
    corr_cols = set(re.findall(r"\b[a-z_][a-z0-9_]*\b", corrected_sql.lower()))
    removed = orig_cols - corr_cols
    added = corr_cols - orig_cols
    if removed and added:
        return "wrong_column"
    return "general_correction"


def ingest_feedback(
    db,
    *,
    plugin_id: str,
    dataset_id: Optional[str],
    question: str,
    original_sql: str,
    corrected_sql: str,
    comment: str = "",
) -> None:
    """
    Process a user correction:
    1. Classify the diff type
    2. Store as high-priority RAG example
    3. Check if we should generate a new prompt rule
    """
    diff_type = classify_correction_type(original_sql, corrected_sql, comment)
    logger.info(f"PromptOptimizer: ingesting feedback, diff_type={diff_type}, plugin={plugin_id}")

    # Store as high-priority RAG example
    try:
        from app.models import RAGExample
        from datetime import datetime
        example = RAGExample(
            plugin_id=plugin_id,
            dataset_id=dataset_id,
            question=question,
            sql=corrected_sql,
            answer_summary=f"User correction ({diff_type}): {comment[:200]}",
            quality_score=0.99,      # user corrections are highest quality
            source="user_correction",
            tags={"diff_type": diff_type, "auto_generated": False},
        )
        db.add(example)
        db.flush()
    except Exception as e:
        logger.warning(f"Failed to store correction as RAG example: {e}")

    # Check if we should generate a new prompt rule
    try:
        _maybe_generate_prompt_rule(db, plugin_id, diff_type, question, original_sql, corrected_sql)
    except Exception as e:
        logger.warning(f"Prompt rule generation failed: {e}")

    try:
        db.commit()
    except Exception as e:
        logger.warning(f"Feedback ingest commit failed: {e}")
        db.rollback()


def _maybe_generate_prompt_rule(
    db,
    plugin_id: str,
    diff_type: str,
    example_question: str,
    original_sql: str,
    corrected_sql: str,
) -> None:
    """Generate a prompt rule if this diff_type has occurred enough times."""
    try:
        from app.models import PromptRule, RAGExample
        # Count recent corrections of this type
        count = (
            db.query(RAGExample)
            .filter(
                RAGExample.plugin_id == plugin_id,
                RAGExample.source == "user_correction",
                RAGExample.tags["diff_type"].astext == diff_type,
            )
            .count()
        )
        if count < _RULE_TRIGGER_COUNT:
            return

        # Check if we already have a rule for this diff_type
        existing = (
            db.query(PromptRule)
            .filter(PromptRule.plugin_id == plugin_id, PromptRule.diff_type == diff_type)
            .first()
        )
        if existing:
            existing.applied_count += 1
            return

        # Generate a rule text based on diff_type
        rule_text = _generate_rule_text(diff_type, example_question, original_sql, corrected_sql)
        if not rule_text:
            return

        rule = PromptRule(
            plugin_id=plugin_id,
            diff_type=diff_type,
            rule_text=rule_text,
        )
        db.add(rule)
        logger.info(f"PromptOptimizer: generated new prompt rule for {plugin_id}.{diff_type}")
    except Exception as e:
        logger.debug(f"_maybe_generate_prompt_rule inner error: {e}")


def _generate_rule_text(diff_type: str, question: str, original: str, corrected: str) -> str:
    """Generate a human-readable rule from the diff type."""
    rules = {
        "wrong_date": (
            "When the user mentions 'last week', use: "
            "WHERE date_col >= CURRENT_DATE - INTERVAL '7 days'. "
            "For 'last month' use DATE_TRUNC('month', CURRENT_DATE - INTERVAL '1 month'). "
            "Never use DATE('YYYY-MM-DD' - INTERVAL ...) syntax."
        ),
        "wrong_column": (
            "Always verify column names against the provided schema before generating SQL. "
            "If a column does not exist, use the closest matching column from the schema."
        ),
        "wrong_aggregation": (
            "Use COUNT(*) or COUNT(DISTINCT col) for counting occurrences. "
            "Use SUM() for totals and revenue. Use AVG() only when asked for averages."
        ),
        "missing_filter": (
            "When the user mentions a specific category, status, or segment, "
            "always add a WHERE clause filter for it."
        ),
        "wrong_join": (
            "Use the JOIN hints in the schema to determine correct join conditions. "
            "Always qualify column names with table aliases when joining."
        ),
        "wrong_groupby": (
            "When grouping by a dimension, include it in both SELECT and GROUP BY. "
            "For time-series, use DATE_TRUNC('day', date_col) in GROUP BY."
        ),
        "general_correction": (
            "Carefully re-read the user's question and the schema before generating SQL. "
            "Check that all column names, aggregations, and filters match the question intent."
        ),
    }
    return rules.get(diff_type, "")


def get_prompt_rules(db, plugin_id: str) -> str:
    """
    Return all active prompt rules for a plugin as a formatted string
    to inject into the LLM system prompt.
    """
    try:
        from app.models import PromptRule
        rules = (
            db.query(PromptRule)
            .filter(PromptRule.plugin_id == plugin_id, PromptRule.is_active == True)  # noqa: E712
            .order_by(PromptRule.applied_count.desc())
            .limit(_MAX_RULES_PER_PLUGIN)
            .all()
        )
        if not rules:
            return ""
        lines = ["## Learned Prompt Rules (from user corrections)\n"]
        for r in rules:
            lines.append(f"- {r.rule_text}")
            r.applied_count += 1
        try:
            db.commit()
        except Exception:
            pass
        return "\n".join(lines)
    except Exception as e:
        logger.debug(f"get_prompt_rules failed: {e}")
        return ""
