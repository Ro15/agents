"""
Dynamic table creator — creates PostgreSQL tables at runtime based on
auto-detected schemas.  Each dataset gets its own table named ds_{short_id}.
"""
from __future__ import annotations

import logging
import re
from typing import List
from uuid import UUID

from sqlalchemy import text, inspect
from sqlalchemy.engine import Engine

from app.schema_detector import ColumnSchema

logger = logging.getLogger(__name__)

# Max identifier length in PostgreSQL
_PG_MAX_IDENT = 63


def table_name_for(dataset_id: str | UUID) -> str:
    """Generate a deterministic table name from a dataset UUID."""
    short = str(dataset_id).replace("-", "")[:12]
    return f"ds_{short}"


def _quote_ident(name: str) -> str:
    """Quote a PostgreSQL identifier to prevent injection."""
    # Remove any existing double quotes
    safe = name.replace('"', '')
    # Truncate to PG limit
    safe = safe[:_PG_MAX_IDENT]
    return f'"{safe}"'


def create_dataset_table(
    engine: Engine,
    dataset_id: str | UUID,
    columns: List[ColumnSchema],
    *,
    drop_existing: bool = False,
) -> str:
    """
    Create a PostgreSQL table for the dataset.

    Returns the table name (e.g. 'ds_abc123def456').
    """
    tbl = table_name_for(dataset_id)

    with engine.begin() as conn:
        if drop_existing:
            conn.execute(text(f"DROP TABLE IF EXISTS {_quote_ident(tbl)} CASCADE"))

        # Check existence
        if engine.dialect.has_table(conn, tbl):
            logger.info(f"Table {tbl} already exists — skipping creation")
            return tbl

        col_defs = [
            f"_row_id UUID PRIMARY KEY DEFAULT gen_random_uuid()"
        ]
        for col in columns:
            null = "" if col.nullable else " NOT NULL"
            col_defs.append(f"{_quote_ident(col.name)} {col.pg_type}{null}")

        ddl = f"CREATE TABLE {_quote_ident(tbl)} (\n  " + ",\n  ".join(col_defs) + "\n)"
        conn.execute(text(ddl))
        logger.info(f"Created table {tbl} with {len(columns)} columns")

    return tbl


def drop_dataset_table(engine: Engine, dataset_id: str | UUID):
    """Drop the dynamic table for a dataset."""
    tbl = table_name_for(dataset_id)
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {_quote_ident(tbl)} CASCADE"))
    logger.info(f"Dropped table {tbl}")


def table_exists(engine: Engine, dataset_id: str | UUID) -> bool:
    """Check if the dynamic table exists."""
    tbl = table_name_for(dataset_id)
    with engine.connect() as conn:
        return engine.dialect.has_table(conn, tbl)


def get_table_columns(engine: Engine, table_name: str) -> list[dict]:
    """Return column info for an existing table via introspection."""
    insp = inspect(engine)
    return [
        {"name": c["name"], "type": str(c["type"]), "nullable": c["nullable"]}
        for c in insp.get_columns(table_name)
    ]
