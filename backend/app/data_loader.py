"""
Data loader — inserts a pandas DataFrame into a PostgreSQL table.
Handles type coercion and chunked inserts for large datasets.
"""

import logging
from typing import Optional

import pandas as pd
from sqlalchemy.engine import Engine

from app.table_manager import _quote_ident

logger = logging.getLogger(__name__)


def _coerce_types(df: pd.DataFrame) -> pd.DataFrame:
    """
    Coerce columns to types that SQLAlchemy / psycopg2 handle well.
    - Convert numpy int/float with NaN to nullable pd types
    - Ensure datetimes are proper Timestamp objects
    """
    for col in df.columns:
        dtype = str(df[col].dtype)
        if dtype.startswith("datetime"):
            df[col] = pd.to_datetime(df[col], errors="coerce")
        elif dtype in ("float64", "Float64"):
            # Leave as-is; NaN-safe
            pass
        elif dtype in ("int64", "Int64"):
            if df[col].isna().any():
                df[col] = df[col].astype("Float64")  # nullable
    return df


def load_dataframe(
    engine: Engine,
    table_name: str,
    df: pd.DataFrame,
    *,
    batch_size: int = 5000,
    if_exists: str = "append",
) -> dict:
    """
    Insert a DataFrame into the target table.

    Returns:
        {"rows_loaded": int, "errors": int}
    """
    df = _coerce_types(df.copy())

    # Drop the _row_id column if present — DB generates it
    if "_row_id" in df.columns:
        df = df.drop(columns=["_row_id"])

    total_rows = len(df)
    loaded = 0
    errors = 0

    # Chunked insert
    for start in range(0, total_rows, batch_size):
        chunk = df.iloc[start : start + batch_size]
        try:
            chunk.to_sql(
                table_name,
                engine,
                if_exists=if_exists,
                index=False,
                method="multi",
            )
            loaded += len(chunk)
        except Exception as e:
            logger.error(f"Error inserting rows {start}–{start + len(chunk)}: {e}")
            errors += len(chunk)
            # Try row-by-row for the failing chunk
            for idx, row in chunk.iterrows():
                try:
                    row.to_frame().T.to_sql(
                        table_name, engine, if_exists="append", index=False
                    )
                    loaded += 1
                    errors -= 1
                except Exception as row_err:
                    logger.debug(f"Skipping row {idx}: {row_err}")

    logger.info(f"Loaded {loaded}/{total_rows} rows into {table_name} ({errors} errors)")
    return {"rows_loaded": loaded, "errors": errors}
