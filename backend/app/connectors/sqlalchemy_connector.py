"""
Shared base class for all SQLAlchemy-based connectors (PostgreSQL, MySQL, MSSQL).
Eliminates duplication of engine creation, test, introspection, and extraction.
"""
from __future__ import annotations

import logging
from typing import List, Optional

import pandas as pd
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from app.connectors.base import BaseConnector

logger = logging.getLogger(__name__)


class SQLAlchemyConnector(BaseConnector):
    """
    Base connector for any SQLAlchemy-compatible database.
    Subclasses only need to set `connector_type`, `_driver_prefix`,
    and `_quote_char`.
    """

    connector_type = "sqlalchemy"
    _driver_prefix: str = ""       # e.g. "mysql+pymysql" — used to fix url scheme
    _quote_char: str = '"'         # identifier quoting: " for PG, ` for MySQL, [] for MSSQL

    def __init__(self, config: dict):
        super().__init__(config)
        self.url = config.get("url", "")
        self._engine: Optional[Engine] = None

    def _fix_url(self, url: str) -> str:
        """Allow subclasses to adjust the connection URL (e.g. add driver)."""
        return url

    def _get_engine(self) -> Engine:
        if not self.url:
            raise ValueError(f"{self.connector_type} connection URL is required in config.url")
        if self._engine is None:
            fixed = self._fix_url(self.url)
            self._engine = create_engine(fixed, pool_pre_ping=True)
            logger.info(f"{self.connector_type} engine created")
        return self._engine

    # ── BaseConnector interface ──────────────────────────────────────

    def test_connection(self) -> tuple[str, str]:
        try:
            eng = self._get_engine()
            with eng.connect() as conn:
                conn.execute(text("SELECT 1"))
            return "connected", f"{self.connector_type} connection successful"
        except Exception as e:
            logger.error(f"{self.connector_type} test_connection failed: {e}")
            return "error", f"Connection failed: {type(e).__name__}: {e}"

    def fetch_tables(self) -> List[str]:
        insp = inspect(self._get_engine())
        return sorted(insp.get_table_names())

    def fetch_schema(self, table: str) -> List[dict]:
        insp = inspect(self._get_engine())
        return [
            {"name": c["name"], "type": str(c["type"]), "nullable": c["nullable"]}
            for c in insp.get_columns(table)
        ]

    def extract_data(self, table_or_query: str, *, limit: Optional[int] = None) -> pd.DataFrame:
        eng = self._get_engine()
        q = table_or_query.strip()
        if not q.upper().startswith("SELECT"):
            qc = self._quote_char
            q = f"SELECT * FROM {qc}{q}{qc}"
        if limit:
            q += f" LIMIT {int(limit)}"
        return pd.read_sql(q, eng)

    def __del__(self):
        if self._engine:
            try:
                self._engine.dispose()
            except Exception:
                pass
