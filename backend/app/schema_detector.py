"""
Schema detector — inspects a pandas DataFrame and produces PostgreSQL-ready
column definitions with profiling stats.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class ColumnSchema:
    name: str
    pg_type: str                    # TEXT, NUMERIC, TIMESTAMP, BOOLEAN, etc.
    pandas_dtype: str               # original pandas dtype string
    nullable: bool = True
    sample_values: list = field(default_factory=list)
    distinct_count: int = 0
    null_count: int = 0
    min_value: Optional[str] = None
    max_value: Optional[str] = None
    mean_value: Optional[float] = None


# Pandas dtype → PostgreSQL type mapping
_DTYPE_MAP = {
    "int64": "BIGINT",
    "int32": "INTEGER",
    "int16": "SMALLINT",
    "Int64": "BIGINT",
    "Int32": "INTEGER",
    "float64": "DOUBLE PRECISION",
    "float32": "REAL",
    "Float64": "DOUBLE PRECISION",
    "bool": "BOOLEAN",
    "boolean": "BOOLEAN",
    "datetime64[ns]": "TIMESTAMP",
    "datetime64[ns, UTC]": "TIMESTAMPTZ",
    "timedelta64[ns]": "INTERVAL",
}


def _pg_type_for(series: pd.Series) -> str:
    """Map a pandas Series dtype to a PostgreSQL column type."""
    dtype_name = str(series.dtype)

    # Direct mapping
    if dtype_name in _DTYPE_MAP:
        return _DTYPE_MAP[dtype_name]

    # Datetime variants
    if "datetime" in dtype_name:
        return "TIMESTAMP"

    # Object (string) — try to detect dates
    if dtype_name == "object":
        non_null = series.dropna()
        if len(non_null) == 0:
            return "TEXT"
        sample = non_null.head(50)
        try:
            pd.to_datetime(sample, format="mixed", dayfirst=False)
            return "TIMESTAMP"
        except (ValueError, TypeError):
            pass
        # Check if all values are numeric strings
        try:
            pd.to_numeric(sample)
            return "DOUBLE PRECISION"
        except (ValueError, TypeError):
            pass
        return "TEXT"

    return "TEXT"


def _safe_str(val: Any) -> Optional[str]:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    return str(val)


def _safe_min_max(non_null: pd.Series, pg_type: str) -> tuple[Optional[str], Optional[str]]:
    """
    Compute min/max safely for profiling.
    Mixed object columns (e.g. strings + ints from Excel) can raise TypeError
    on direct comparisons, so text-like fields are compared as strings.
    """
    if len(non_null) == 0:
        return None, None

    try:
        if pg_type in {"BIGINT", "INTEGER", "SMALLINT", "DOUBLE PRECISION", "REAL", "NUMERIC", "TIMESTAMP", "TIMESTAMPTZ", "BOOLEAN", "INTERVAL"}:
            return _safe_str(non_null.min()), _safe_str(non_null.max())

        text_values = non_null.astype(str)
        return _safe_str(text_values.min()), _safe_str(text_values.max())
    except TypeError:
        # Fallback for mixed, non-orderable Python objects.
        text_values = non_null.astype(str)
        return _safe_str(text_values.min()), _safe_str(text_values.max())
    except Exception:
        logger.debug("Could not compute min/max for column %s", non_null.name, exc_info=True)
        return None, None


def detect_schema(df: pd.DataFrame) -> List[ColumnSchema]:
    """
    Inspect a DataFrame and return column definitions with profiling stats.
    Also attempts to coerce object columns that look like dates/numbers.
    """
    columns: List[ColumnSchema] = []

    for col_name in df.columns:
        series = df[col_name]
        pg_type = _pg_type_for(series)

        # Attempt automatic coercion for better downstream handling
        if pg_type == "TIMESTAMP" and str(series.dtype) == "object":
            try:
                df[col_name] = pd.to_datetime(series, format="mixed", dayfirst=False)
                series = df[col_name]
            except Exception:
                pg_type = "TEXT"

        if pg_type == "DOUBLE PRECISION" and str(series.dtype) == "object":
            try:
                df[col_name] = pd.to_numeric(series)
                series = df[col_name]
            except Exception:
                pg_type = "TEXT"

        non_null = series.dropna()
        null_count = int(series.isna().sum())
        distinct_count = int(non_null.nunique()) if len(non_null) > 0 else 0
        samples = [str(v) for v in non_null.head(5).tolist()]

        min_val, max_val = _safe_min_max(non_null, pg_type)
        mean_val = None
        if pg_type in ("BIGINT", "INTEGER", "SMALLINT", "DOUBLE PRECISION", "REAL", "NUMERIC"):
            try:
                mean_val = float(non_null.mean())
            except Exception:
                pass

        columns.append(ColumnSchema(
            name=col_name,
            pg_type=pg_type,
            pandas_dtype=str(series.dtype),
            nullable=null_count > 0,
            sample_values=samples,
            distinct_count=distinct_count,
            null_count=null_count,
            min_value=min_val,
            max_value=max_val,
            mean_value=mean_val,
        ))

    logger.info(f"Detected schema: {len(columns)} columns")
    return columns
