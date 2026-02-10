"""Snowflake data connector (optional dependency)."""
from __future__ import annotations

import logging
from typing import List, Optional

import pandas as pd

from app.connectors.base import BaseConnector

logger = logging.getLogger(__name__)


class SnowflakeConnector(BaseConnector):
    connector_type = "snowflake"

    def __init__(self, config: dict):
        super().__init__(config)
        self.account = config.get("account", "")
        self.user = config.get("user", "")
        self.password = config.get("password", "")
        self.warehouse = config.get("warehouse", "")
        self.database = config.get("database", "")
        self.schema = config.get("schema", "PUBLIC")

    def _get_connection(self):
        try:
            import snowflake.connector
        except ImportError:
            raise RuntimeError("Install 'snowflake-connector-python' to use Snowflake connector")
        return snowflake.connector.connect(
            account=self.account,
            user=self.user,
            password=self.password,
            warehouse=self.warehouse,
            database=self.database,
            schema=self.schema,
        )

    def test_connection(self) -> tuple[str, str]:
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            cur.execute("SELECT CURRENT_VERSION()")
            version = cur.fetchone()[0]
            cur.close()
            conn.close()
            return "connected", f"Snowflake connected (version: {version})"
        except Exception as e:
            return "error", f"Connection failed: {type(e).__name__}: {e}"

    def fetch_tables(self) -> List[str]:
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute("SHOW TABLES")
        tables = [row[1] for row in cur.fetchall()]
        cur.close()
        conn.close()
        return tables

    def fetch_schema(self, table: str) -> List[dict]:
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute(f"DESCRIBE TABLE \"{table}\"")
        cols = [
            {"name": row[0], "type": row[1], "nullable": row[3] == "Y"}
            for row in cur.fetchall()
        ]
        cur.close()
        conn.close()
        return cols

    def extract_data(self, table_or_query: str, *, limit: Optional[int] = None) -> pd.DataFrame:
        conn = self._get_connection()
        q = table_or_query.strip()
        if not q.upper().startswith("SELECT"):
            q = f'SELECT * FROM "{q}"'
        if limit:
            q += f" LIMIT {int(limit)}"
        cur = conn.cursor()
        cur.execute(q)
        columns = [desc[0] for desc in cur.description]
        data = cur.fetchall()
        cur.close()
        conn.close()
        return pd.DataFrame(data, columns=columns)
