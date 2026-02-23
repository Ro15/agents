"""
Cross-Dataset Federation Service — Task 2.3
Auto-detects joinable columns across datasets in the same plugin.
Injects JOIN hints into the LLM schema context.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_OVERLAP_THRESHOLD = 0.7   # 70% value overlap to consider a join candidate


@dataclass
class JoinHint:
    left_table: str
    left_column: str
    right_table: str
    right_column: str
    left_dataset_id: str
    right_dataset_id: str
    left_type: str
    right_type: str
    overlap_score: float = 0.0    # 0–1 similarity score
    example_values: list[str] = field(default_factory=list)

    def to_sql_comment(self) -> str:
        pct = int(self.overlap_score * 100)
        return (
            f"-- JOIN HINT: {self.left_table}.{self.left_column} "
            f"↔ {self.right_table}.{self.right_column} "
            f"({self.left_type}, ~{pct}% value overlap)\n"
            f"-- Example: JOIN {self.right_table} r ON l.{self.left_column} = r.{self.right_column}"
        )

    def to_dict(self) -> dict:
        return {
            "left_table": self.left_table,
            "left_column": self.left_column,
            "right_table": self.right_table,
            "right_column": self.right_column,
            "left_dataset_id": self.left_dataset_id,
            "right_dataset_id": self.right_dataset_id,
            "overlap_score": round(self.overlap_score, 3),
            "example_values": self.example_values[:5],
        }


class FederationService:
    """
    Discovers join-able columns across multiple datasets in a plugin.
    Uses column name matching + data type compatibility + optional value overlap.
    """

    def discover_joins(
        self,
        plugin_id: str,
        db: Session,
    ) -> list[JoinHint]:
        """
        Find all join candidates across active datasets for a plugin.
        Returns list of JoinHint objects sorted by overlap_score descending.
        """
        from app.models import Dataset, ColumnProfile
        datasets = (
            db.query(Dataset)
            .filter(Dataset.plugin_id == plugin_id, Dataset.is_deleted == False)  # noqa: E712
            .filter(Dataset.schema_type == "dynamic")
            .all()
        )
        if len(datasets) < 2:
            return []

        # Build column profile map: {dataset_id: [(column_name, data_type, table_name)]}
        profile_map: dict[str, list[dict]] = {}
        for ds in datasets:
            profiles = db.query(ColumnProfile).filter(ColumnProfile.dataset_id == ds.dataset_id).all()
            profile_map[str(ds.dataset_id)] = [
                {
                    "column_name": cp.column_name,
                    "data_type": cp.data_type or "TEXT",
                    "table_name": ds.table_name or f"ds_{str(ds.dataset_id).replace('-', '')[:12]}",
                    "dataset_id": str(ds.dataset_id),
                    "sample_values": cp.sample_values or [],
                }
                for cp in profiles
            ]

        hints: list[JoinHint] = []
        ds_ids = list(profile_map.keys())

        for i in range(len(ds_ids)):
            for j in range(i + 1, len(ds_ids)):
                left_profiles = profile_map[ds_ids[i]]
                right_profiles = profile_map[ds_ids[j]]
                hints.extend(self._find_join_candidates(left_profiles, right_profiles))

        hints.sort(key=lambda h: h.overlap_score, reverse=True)
        return hints[:20]  # cap at 20 hints

    @staticmethod
    def _find_join_candidates(
        left_profiles: list[dict],
        right_profiles: list[dict],
    ) -> list[JoinHint]:
        """
        Find column pairs that are likely join keys based on:
        1. Exact column name match
        2. Compatible data types (both text, both integer, etc.)
        3. Shared sample values
        """
        hints = []
        right_by_name = {p["column_name"].lower(): p for p in right_profiles}

        for lp in left_profiles:
            col_name = lp["column_name"].lower()
            rp = right_by_name.get(col_name)
            if not rp:
                # Try partial match (e.g., "product_id" ↔ "id")
                rp = next(
                    (p for p in right_profiles if col_name.endswith("_" + p["column_name"].lower())
                     or p["column_name"].lower().endswith("_" + col_name)),
                    None
                )
            if not rp:
                continue

            # Type compatibility
            if not _types_compatible(lp["data_type"], rp["data_type"]):
                continue

            # Skip highly generic/non-join columns
            skip_cols = {"id", "created_at", "updated_at", "timestamp", "date", "index"}
            if lp["column_name"].lower() in skip_cols and not lp["column_name"].lower().endswith("_id"):
                continue

            # Compute sample value overlap
            left_vals = set(str(v) for v in (lp.get("sample_values") or []) if v)
            right_vals = set(str(v) for v in (rp.get("sample_values") or []) if v)
            if left_vals and right_vals:
                overlap = len(left_vals & right_vals) / len(left_vals | right_vals)
            else:
                # Name match alone gives a moderate score
                overlap = 0.5

            if overlap < 0.1:
                continue

            hints.append(JoinHint(
                left_table=lp["table_name"],
                left_column=lp["column_name"],
                right_table=rp["table_name"],
                right_column=rp["column_name"],
                left_dataset_id=lp["dataset_id"],
                right_dataset_id=rp["dataset_id"],
                left_type=lp["data_type"],
                right_type=rp["data_type"],
                overlap_score=overlap,
                example_values=sorted(left_vals & right_vals)[:5] if left_vals & right_vals else [],
            ))

        return hints

    def build_federation_schema_context(
        self,
        hints: list[JoinHint],
    ) -> str:
        """
        Returns a formatted schema context block with JOIN hints for the LLM prompt.
        """
        if not hints:
            return ""
        lines = ["\n## Cross-Dataset JOIN Hints (auto-detected)\n"]
        lines.append("You can JOIN these datasets to answer cross-dataset questions:\n")
        for hint in hints[:10]:
            lines.append(hint.to_sql_comment())
            lines.append("")
        return "\n".join(lines)


def _types_compatible(type_a: str, type_b: str) -> bool:
    """Check if two Postgres types are compatible for joining."""
    a = (type_a or "").lower()
    b = (type_b or "").lower()
    text_types = {"text", "varchar", "character varying", "char", "uuid"}
    int_types = {"integer", "bigint", "smallint", "int4", "int8"}
    num_types = {"numeric", "decimal", "real", "double precision", "float"}

    def category(t: str) -> str:
        for group, members in [("text", text_types), ("int", int_types), ("num", num_types)]:
            if any(m in t for m in members):
                return group
        return "other"

    return category(a) == category(b) and category(a) != "other"


# Module-level singleton
_federation_service = FederationService()


def get_federation_hints(plugin_id: str, db: Session) -> list[JoinHint]:
    """Public API: discover join hints for a plugin."""
    return _federation_service.discover_joins(plugin_id, db)


def get_federation_schema_context(hints: list[JoinHint]) -> str:
    """Build schema context block from join hints."""
    return _federation_service.build_federation_schema_context(hints)
