"""
Root Cause Analysis Engine — Task 2.1
When a metric shows >10% change, automatically finds top contributing dimensions.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional, Any

logger = logging.getLogger(__name__)

_TRIGGER_THRESHOLD = 0.10   # 10% change triggers RCA


@dataclass
class DimensionContribution:
    dimension: str
    value: str
    current: float
    previous: float
    delta: float
    delta_pct: float
    contribution_pct: float   # share of total delta

    def to_dict(self) -> dict:
        return {
            "dimension": self.dimension,
            "value": self.value,
            "current": round(self.current, 4),
            "previous": round(self.previous, 4),
            "delta": round(self.delta, 4),
            "delta_pct": round(self.delta_pct * 100, 2),
            "contribution_pct": round(self.contribution_pct * 100, 2),
        }


@dataclass
class RCAReport:
    metric: str
    table: str
    total_delta: float
    total_delta_pct: float
    top_contributors: list[DimensionContribution] = field(default_factory=list)
    explanation: str = ""
    follow_up_questions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "metric": self.metric,
            "table": self.table,
            "total_delta": round(self.total_delta, 4),
            "total_delta_pct": round(self.total_delta_pct * 100, 2),
            "top_contributors": [c.to_dict() for c in self.top_contributors],
            "explanation": self.explanation,
            "follow_up_questions": self.follow_up_questions,
        }


class RCAEngine:
    """
    Runs root cause analysis by breaking a metric down by each categorical dimension.
    Compares the current period to the previous period of equal length.
    """

    MAX_DIMS = 5
    MAX_CONTRIBUTORS = 3

    def analyze(
        self,
        *,
        table: str,
        metric_col: str,
        date_col: str,
        conn,                         # SQLAlchemy connection
        period_days: int = 7,
    ) -> Optional[RCAReport]:
        """
        Discover categorical columns in the table, compute their delta over
        current vs. previous period, return a ranked RCA report.
        """
        try:
            dims = self._discover_dimensions(table, conn)[:self.MAX_DIMS]
            if not dims:
                return None

            # Compute overall delta first
            overall = self._compute_overall_delta(table, metric_col, date_col, period_days, conn)
            if overall is None:
                return None
            total_current, total_previous = overall
            total_delta = total_current - total_previous
            if total_previous == 0:
                return None
            total_delta_pct = total_delta / abs(total_previous)

            # Only run full RCA if change is meaningful
            if abs(total_delta_pct) < _TRIGGER_THRESHOLD:
                return None

            contributions: list[DimensionContribution] = []
            for dim in dims:
                dim_contribs = self._compute_dim_delta(
                    table, metric_col, date_col, dim, period_days, total_delta, conn
                )
                contributions.extend(dim_contribs)

            # Sort by absolute contribution descending
            contributions.sort(key=lambda c: abs(c.delta), reverse=True)
            top = contributions[:self.MAX_CONTRIBUTORS]

            explanation = self._build_explanation(metric_col, total_delta_pct, top)
            follow_ups = self._build_follow_ups(metric_col, top)

            return RCAReport(
                metric=metric_col,
                table=table,
                total_delta=total_delta,
                total_delta_pct=total_delta_pct,
                top_contributors=top,
                explanation=explanation,
                follow_up_questions=follow_ups,
            )
        except Exception as e:
            logger.warning(f"RCA failed for {table}.{metric_col}: {e}")
            return None

    def _discover_dimensions(self, table: str, conn) -> list[str]:
        """Find low-cardinality text columns suitable for grouping."""
        try:
            from sqlalchemy import text
            sql = text(f"""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_name = :tbl
                  AND data_type IN ('character varying', 'varchar', 'text', 'char')
                ORDER BY column_name
                LIMIT 20
            """)
            rows = conn.execute(sql, {"tbl": table}).fetchall()
            return [r[0] for r in rows]
        except Exception as e:
            logger.debug(f"Dimension discovery failed: {e}")
            return []

    def _compute_overall_delta(
        self,
        table: str,
        metric_col: str,
        date_col: str,
        period_days: int,
        conn,
    ) -> Optional[tuple[float, float]]:
        try:
            from sqlalchemy import text
            sql = text(f"""
                SELECT
                    SUM(CASE WHEN {date_col} >= CURRENT_DATE - INTERVAL '{period_days} days'
                             THEN CAST({metric_col} AS NUMERIC) ELSE 0 END) AS current_val,
                    SUM(CASE WHEN {date_col} >= CURRENT_DATE - INTERVAL '{period_days * 2} days'
                             AND {date_col} < CURRENT_DATE - INTERVAL '{period_days} days'
                             THEN CAST({metric_col} AS NUMERIC) ELSE 0 END) AS previous_val
                FROM {table}
                WHERE {date_col} >= CURRENT_DATE - INTERVAL '{period_days * 2} days'
            """)
            row = conn.execute(sql).fetchone()
            if row is None:
                return None
            current_val = float(row[0] or 0)
            previous_val = float(row[1] or 0)
            return current_val, previous_val
        except Exception as e:
            logger.debug(f"Overall delta compute failed: {e}")
            return None

    def _compute_dim_delta(
        self,
        table: str,
        metric_col: str,
        date_col: str,
        dim_col: str,
        period_days: int,
        total_delta: float,
        conn,
    ) -> list[DimensionContribution]:
        try:
            from sqlalchemy import text
            sql = text(f"""
                SELECT
                    {dim_col} AS dim_val,
                    SUM(CASE WHEN {date_col} >= CURRENT_DATE - INTERVAL '{period_days} days'
                             THEN CAST({metric_col} AS NUMERIC) ELSE 0 END) AS current_val,
                    SUM(CASE WHEN {date_col} >= CURRENT_DATE - INTERVAL '{period_days * 2} days'
                             AND {date_col} < CURRENT_DATE - INTERVAL '{period_days} days'
                             THEN CAST({metric_col} AS NUMERIC) ELSE 0 END) AS previous_val
                FROM {table}
                WHERE {date_col} >= CURRENT_DATE - INTERVAL '{period_days * 2} days'
                GROUP BY {dim_col}
                ORDER BY ABS(
                    SUM(CASE WHEN {date_col} >= CURRENT_DATE - INTERVAL '{period_days} days'
                             THEN CAST({metric_col} AS NUMERIC) ELSE 0 END)
                    - SUM(CASE WHEN {date_col} >= CURRENT_DATE - INTERVAL '{period_days * 2} days'
                               AND {date_col} < CURRENT_DATE - INTERVAL '{period_days} days'
                               THEN CAST({metric_col} AS NUMERIC) ELSE 0 END)
                ) DESC
                LIMIT 5
            """)
            rows = conn.execute(sql).fetchall()
            results = []
            for row in rows:
                dim_val = str(row[0] or "N/A")
                current = float(row[1] or 0)
                previous = float(row[2] or 0)
                delta = current - previous
                delta_pct = delta / abs(previous) if previous != 0 else 0.0
                contribution_pct = delta / total_delta if total_delta != 0 else 0.0
                results.append(DimensionContribution(
                    dimension=dim_col,
                    value=dim_val,
                    current=current,
                    previous=previous,
                    delta=delta,
                    delta_pct=delta_pct,
                    contribution_pct=contribution_pct,
                ))
            return results
        except Exception as e:
            logger.debug(f"Dim delta compute failed for {dim_col}: {e}")
            return []

    @staticmethod
    def _build_explanation(metric: str, delta_pct: float, contributors: list[DimensionContribution]) -> str:
        direction = "increased" if delta_pct > 0 else "decreased"
        explanation = f"{metric} {direction} {abs(delta_pct) * 100:.1f}%."
        if contributors:
            top = contributors[0]
            explanation += (
                f" The largest contributor was **{top.dimension}={top.value}** "
                f"({'+' if top.delta_pct > 0 else ''}{top.delta_pct * 100:.1f}%, "
                f"{abs(top.contribution_pct) * 100:.0f}% of total change)."
            )
        return explanation

    @staticmethod
    def _build_follow_ups(metric: str, contributors: list[DimensionContribution]) -> list[str]:
        follow_ups = []
        for c in contributors[:2]:
            follow_ups.append(
                f"Show me {metric} trend for {c.dimension} = '{c.value}' over the last 30 days."
            )
        if contributors:
            dim = contributors[0].dimension
            follow_ups.append(f"Which {dim} had the highest {metric} growth last week?")
        return follow_ups


# Module-level singleton
_rca_engine = RCAEngine()


def run_rca(
    *,
    table: str,
    metric_col: str,
    date_col: str,
    conn,
    period_days: int = 7,
) -> Optional[RCAReport]:
    """Run RCA and return a report dict, or None if not applicable."""
    return _rca_engine.analyze(
        table=table,
        metric_col=metric_col,
        date_col=date_col,
        conn=conn,
        period_days=period_days,
    )
