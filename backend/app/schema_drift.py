"""
Schema Drift Detector — Task 3.1
Compares old vs. new column profiles after every upload/sync.
Detects: removed columns, type changes, null-rate spikes, new columns.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class DriftEvent:
    drift_type: str      # column_removed | type_changed | null_spike | column_added
    column_name: str
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    severity: str = "medium"   # low | medium | high | critical
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "drift_type": self.drift_type,
            "column_name": self.column_name,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "severity": self.severity,
            "message": self.message,
        }


@dataclass
class DriftReport:
    dataset_id: str
    events: list[DriftEvent] = field(default_factory=list)

    @property
    def has_critical(self) -> bool:
        return any(e.severity == "critical" for e in self.events)

    @property
    def has_warnings(self) -> bool:
        return bool(self.events)

    @property
    def summary(self) -> str:
        if not self.events:
            return "No schema drift detected."
        parts = []
        counts = {}
        for e in self.events:
            counts[e.drift_type] = counts.get(e.drift_type, 0) + 1
        for dtype, cnt in counts.items():
            parts.append(f"{cnt} {dtype.replace('_', ' ')}(s)")
        return "Schema drift: " + ", ".join(parts) + "."

    def to_dict(self) -> dict:
        return {
            "dataset_id": self.dataset_id,
            "has_critical": self.has_critical,
            "has_warnings": self.has_warnings,
            "summary": self.summary,
            "events": [e.to_dict() for e in self.events],
        }


class SchemaDriftDetector:
    """
    Compares two lists of column profile dicts:
      old_profiles: [{"column_name": ..., "data_type": ..., "null_count": ..., "row_count": ...}]
      new_profiles: same shape
    """

    NULL_SPIKE_THRESHOLD = 0.15   # 15 percentage-point increase in null rate triggers warning
    NULL_CRITICAL_THRESHOLD = 0.5  # 50 pp increase is critical

    def compare(
        self,
        dataset_id: str,
        old_profiles: list[dict],
        new_profiles: list[dict],
        old_row_count: int = 0,
        new_row_count: int = 0,
    ) -> DriftReport:
        report = DriftReport(dataset_id=dataset_id)

        old_map = {p["column_name"]: p for p in old_profiles}
        new_map = {p["column_name"]: p for p in new_profiles}

        # Removed columns
        for col in old_map:
            if col not in new_map:
                report.events.append(DriftEvent(
                    drift_type="column_removed",
                    column_name=col,
                    old_value=old_map[col].get("data_type"),
                    severity="critical",
                    message=f"Column '{col}' was removed from the dataset.",
                ))

        # Added columns
        for col in new_map:
            if col not in old_map:
                report.events.append(DriftEvent(
                    drift_type="column_added",
                    column_name=col,
                    new_value=new_map[col].get("data_type"),
                    severity="low",
                    message=f"New column '{col}' detected in the dataset.",
                ))

        # Type changes and null spikes for shared columns
        for col in old_map:
            if col not in new_map:
                continue
            old_p = old_map[col]
            new_p = new_map[col]

            # Type change
            old_type = (old_p.get("data_type") or "").strip().upper()
            new_type = (new_p.get("data_type") or "").strip().upper()
            if old_type and new_type and old_type != new_type:
                severity = "high" if self._is_breaking_type_change(old_type, new_type) else "medium"
                report.events.append(DriftEvent(
                    drift_type="type_changed",
                    column_name=col,
                    old_value=old_type,
                    new_value=new_type,
                    severity=severity,
                    message=f"Column '{col}' type changed from {old_type} to {new_type}.",
                ))

            # Null rate spike
            old_null = old_p.get("null_count") or 0
            new_null = new_p.get("null_count") or 0
            old_rows = old_row_count or 1
            new_rows = new_row_count or 1
            old_null_rate = old_null / old_rows
            new_null_rate = new_null / new_rows
            delta = new_null_rate - old_null_rate
            if delta >= self.NULL_CRITICAL_THRESHOLD:
                severity = "critical"
            elif delta >= self.NULL_SPIKE_THRESHOLD:
                severity = "high"
            else:
                severity = None
            if severity:
                report.events.append(DriftEvent(
                    drift_type="null_spike",
                    column_name=col,
                    old_value=f"{old_null_rate:.1%}",
                    new_value=f"{new_null_rate:.1%}",
                    severity=severity,
                    message=(
                        f"Column '{col}' null rate increased from {old_null_rate:.1%} "
                        f"to {new_null_rate:.1%} (+{delta:.1%})."
                    ),
                ))

        if report.events:
            logger.warning(
                f"Schema drift detected for dataset {dataset_id}: "
                f"{len(report.events)} event(s). Summary: {report.summary}"
            )
        return report

    @staticmethod
    def _is_breaking_type_change(old_type: str, new_type: str) -> bool:
        """A type change is 'breaking' if it narrows or fundamentally changes the type."""
        numeric_types = {"INTEGER", "BIGINT", "NUMERIC", "FLOAT", "DOUBLE PRECISION", "REAL"}
        text_types = {"TEXT", "VARCHAR", "CHAR", "CHARACTER VARYING"}
        date_types = {"DATE", "TIMESTAMP", "TIMESTAMPTZ", "TIMESTAMP WITH TIME ZONE"}
        # numeric → text is usually fine (widening); text → numeric is breaking
        if old_type in text_types and new_type in numeric_types:
            return True
        # date → text breaking
        if old_type in date_types and new_type in text_types:
            return True
        return False


def compare_profiles_from_orm(
    dataset_id: str,
    old_col_profiles,   # list of ColumnProfile ORM objects
    new_col_schemas,    # list of ColumnSchema dataclass objects (from schema_detector)
    old_row_count: int = 0,
    new_row_count: int = 0,
) -> DriftReport:
    """
    Convenience wrapper that converts ORM objects / dataclasses to the plain dict
    format expected by SchemaDriftDetector.compare().
    """
    old_profiles = [
        {
            "column_name": cp.column_name,
            "data_type": cp.data_type or "",
            "null_count": cp.null_count or 0,
        }
        for cp in old_col_profiles
    ]
    new_profiles = [
        {
            "column_name": cs.name,
            "data_type": cs.pg_type or "",
            "null_count": cs.null_count or 0,
        }
        for cs in new_col_schemas
    ]
    detector = SchemaDriftDetector()
    return detector.compare(
        dataset_id=str(dataset_id),
        old_profiles=old_profiles,
        new_profiles=new_profiles,
        old_row_count=old_row_count,
        new_row_count=new_row_count,
    )
