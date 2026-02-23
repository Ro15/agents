"""
Cohort & Retention Analysis Engine — Task 2.4
Pre-built SQL templates for retention, funnel, LTV, and churn analysis.
Activates when question contains cohort/retention/funnel keywords.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# ── Intent keywords ───────────────────────────────────────────────────────

COHORT_KEYWORDS = ["cohort", "retention", "returning", "churn", "repeat"]
FUNNEL_KEYWORDS = ["funnel", "conversion", "drop-off", "dropoff", "step", "pipeline"]
LTV_KEYWORDS = ["lifetime value", "ltv", "clv", "customer value", "customer lifetime"]
RFM_KEYWORDS = ["rfm", "recency", "frequency", "monetary", "segment customer", "customer segment"]


def detect_cohort_intent(question: str) -> Optional[str]:
    """Returns 'retention' | 'funnel' | 'ltv' | 'rfm' | None."""
    q = question.lower()
    if any(kw in q for kw in COHORT_KEYWORDS):
        return "retention"
    if any(kw in q for kw in FUNNEL_KEYWORDS):
        return "funnel"
    if any(kw in q for kw in LTV_KEYWORDS):
        return "ltv"
    if any(kw in q for kw in RFM_KEYWORDS):
        return "rfm"
    return None


class CohortEngine:
    """
    Generates cohort analysis SQL from column mapping.
    column_map must contain:
      - user_col: column name identifying the user/customer
      - date_col: transaction/event date column
      - table: table name
      - value_col (optional): revenue/amount column for LTV
      - event_col (optional): event/step column for funnel
    """

    def build_query(self, intent: str, column_map: dict) -> Optional[str]:
        """Return a SQL string for the given cohort intent."""
        builders = {
            "retention": self._retention_sql,
            "funnel": self._funnel_sql,
            "ltv": self._ltv_sql,
            "rfm": self._rfm_sql,
        }
        builder = builders.get(intent)
        if not builder:
            return None
        try:
            return builder(column_map)
        except Exception as e:
            logger.warning(f"CohortEngine.build_query failed for intent={intent}: {e}")
            return None

    @staticmethod
    def _retention_sql(cm: dict) -> str:
        tbl = cm["table"]
        user = cm["user_col"]
        date = cm["date_col"]
        return f"""
WITH cohorts AS (
    SELECT
        {user} AS user_id,
        DATE_TRUNC('month', MIN({date}::TIMESTAMP)) AS cohort_month
    FROM {tbl}
    GROUP BY {user}
),
activity AS (
    SELECT
        t.{user} AS user_id,
        DATE_TRUNC('month', t.{date}::TIMESTAMP) AS activity_month,
        c.cohort_month,
        EXTRACT(EPOCH FROM (
            DATE_TRUNC('month', t.{date}::TIMESTAMP) - c.cohort_month
        )) / (30.0 * 86400) AS period_number
    FROM {tbl} t
    JOIN cohorts c ON t.{user} = c.user_id
)
SELECT
    cohort_month::DATE AS cohort_month,
    period_number::INTEGER AS period,
    COUNT(DISTINCT user_id) AS users
FROM activity
WHERE period_number >= 0 AND period_number <= 12
GROUP BY 1, 2
ORDER BY 1, 2
LIMIT 200
""".strip()

    @staticmethod
    def _funnel_sql(cm: dict) -> str:
        tbl = cm["table"]
        user = cm.get("user_col", "user_id")
        date = cm["date_col"]
        event_col = cm.get("event_col", "event_type")
        return f"""
SELECT
    {event_col} AS step,
    COUNT(DISTINCT {user}) AS users,
    ROUND(
        100.0 * COUNT(DISTINCT {user}) /
        NULLIF(MAX(COUNT(DISTINCT {user})) OVER (), 0),
        2
    ) AS conversion_rate_pct
FROM {tbl}
WHERE {date}::TIMESTAMP >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY {event_col}
ORDER BY users DESC
LIMIT 20
""".strip()

    @staticmethod
    def _ltv_sql(cm: dict) -> str:
        tbl = cm["table"]
        user = cm.get("user_col", "customer_id")
        date = cm["date_col"]
        value = cm.get("value_col", "amount")
        return f"""
SELECT
    {user} AS customer_id,
    COUNT(*) AS total_orders,
    SUM(CAST({value} AS NUMERIC)) AS total_revenue,
    AVG(CAST({value} AS NUMERIC)) AS avg_order_value,
    MIN({date}::TIMESTAMP)::DATE AS first_order_date,
    MAX({date}::TIMESTAMP)::DATE AS last_order_date,
    EXTRACT(DAY FROM (MAX({date}::TIMESTAMP) - MIN({date}::TIMESTAMP))) AS days_active,
    ROUND(
        SUM(CAST({value} AS NUMERIC)) /
        NULLIF(EXTRACT(MONTH FROM AGE(MAX({date}::TIMESTAMP), MIN({date}::TIMESTAMP))) + 1, 0),
        2
    ) AS monthly_ltv
FROM {tbl}
GROUP BY {user}
HAVING COUNT(*) > 1
ORDER BY total_revenue DESC
LIMIT 100
""".strip()

    @staticmethod
    def _rfm_sql(cm: dict) -> str:
        tbl = cm["table"]
        user = cm.get("user_col", "customer_id")
        date = cm["date_col"]
        value = cm.get("value_col", "amount")
        return f"""
WITH rfm_base AS (
    SELECT
        {user} AS customer_id,
        CURRENT_DATE - MAX({date}::DATE) AS recency_days,
        COUNT(*) AS frequency,
        SUM(CAST({value} AS NUMERIC)) AS monetary
    FROM {tbl}
    GROUP BY {user}
),
rfm_scored AS (
    SELECT
        customer_id,
        recency_days,
        frequency,
        monetary,
        NTILE(5) OVER (ORDER BY recency_days DESC) AS r_score,
        NTILE(5) OVER (ORDER BY frequency) AS f_score,
        NTILE(5) OVER (ORDER BY monetary) AS m_score
    FROM rfm_base
)
SELECT
    customer_id,
    recency_days,
    frequency,
    ROUND(monetary, 2) AS monetary,
    r_score,
    f_score,
    m_score,
    (r_score + f_score + m_score) AS rfm_total,
    CASE
        WHEN r_score >= 4 AND f_score >= 4 AND m_score >= 4 THEN 'Champions'
        WHEN r_score >= 3 AND f_score >= 3 THEN 'Loyal Customers'
        WHEN r_score >= 4 THEN 'Recent Customers'
        WHEN f_score >= 4 THEN 'Frequent Buyers'
        WHEN r_score <= 2 AND f_score <= 2 THEN 'At Risk'
        ELSE 'Potential Loyalists'
    END AS segment
FROM rfm_scored
ORDER BY rfm_total DESC
LIMIT 200
""".strip()

    def discover_column_map(self, col_profiles: list) -> dict:
        """
        Auto-discover user, date, value, and event columns from ColumnProfile objects.
        Returns a column_map dict suitable for build_query().
        """
        user_hints = ["user", "customer", "client", "member", "buyer", "account"]
        date_hints = ["date", "time", "at", "created", "ordered", "purchased"]
        value_hints = ["amount", "price", "revenue", "total", "value", "cost", "sales"]
        event_hints = ["event", "action", "step", "stage", "status", "type"]

        user_col = date_col = value_col = event_col = table_name = None
        for cp in col_profiles:
            col = cp.column_name.lower()
            dtype = (cp.data_type or "").lower()
            if any(h in col for h in user_hints) and not user_col:
                user_col = cp.column_name
            if any(h in col for h in date_hints) and ("date" in dtype or "time" in dtype) and not date_col:
                date_col = cp.column_name
            if any(h in col for h in value_hints) and not value_col and ("numeric" in dtype or "int" in dtype or "float" in dtype):
                value_col = cp.column_name
            if any(h in col for h in event_hints) and not event_col:
                event_col = cp.column_name

        return {
            "user_col": user_col or "id",
            "date_col": date_col or "created_at",
            "value_col": value_col,
            "event_col": event_col,
        }


# Module-level singleton
_cohort_engine = CohortEngine()


def build_cohort_sql(intent: str, column_map: dict) -> Optional[str]:
    return _cohort_engine.build_query(intent, column_map)


def auto_column_map(table: str, col_profiles: list) -> dict:
    cm = _cohort_engine.discover_column_map(col_profiles)
    cm["table"] = table
    return cm
