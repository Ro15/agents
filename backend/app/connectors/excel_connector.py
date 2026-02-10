"""Excel file connector — reads .xlsx/.xls from a file path or URL."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

import pandas as pd

from app.connectors.base import BaseConnector

logger = logging.getLogger(__name__)


class ExcelConnector(BaseConnector):
    connector_type = "excel"

    def __init__(self, config: dict):
        super().__init__(config)
        self.file_path = config.get("url", config.get("file_path", ""))

    def test_connection(self) -> tuple[str, str]:
        try:
            p = Path(self.file_path)
            if not p.exists():
                return "error", f"File not found: {self.file_path}"
            xls = pd.ExcelFile(self.file_path, engine="openpyxl")
            return "connected", f"Excel file readable ({len(xls.sheet_names)} sheets)"
        except Exception as e:
            return "error", f"Failed to read Excel: {type(e).__name__}: {e}"

    def fetch_tables(self) -> List[str]:
        xls = pd.ExcelFile(self.file_path, engine="openpyxl")
        return xls.sheet_names

    def fetch_schema(self, table: str) -> List[dict]:
        df = pd.read_excel(self.file_path, sheet_name=table, engine="openpyxl", nrows=5)
        return [{"name": c, "type": str(df[c].dtype), "nullable": True} for c in df.columns]

    def extract_data(self, table_or_query: str, *, limit: Optional[int] = None) -> pd.DataFrame:
        nrows = limit if limit else None
        return pd.read_excel(self.file_path, sheet_name=table_or_query, engine="openpyxl", nrows=nrows)
