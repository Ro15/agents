"""Google Sheets data connector."""
from __future__ import annotations

import logging
from typing import List, Optional

import pandas as pd

from app.connectors.base import BaseConnector

logger = logging.getLogger(__name__)


class SheetsConnector(BaseConnector):
    connector_type = "sheets"

    def __init__(self, config: dict):
        super().__init__(config)
        self.spreadsheet_url = config.get("url", "")
        self.credentials_json = config.get("credentials_json")
        self.api_key = config.get("api_key")

    def _get_client(self):
        try:
            import gspread
        except ImportError:
            raise RuntimeError("Install 'gspread' and 'google-auth' to use Google Sheets connector")

        if self.credentials_json:
            from google.oauth2.service_account import Credentials
            import json
            creds_data = json.loads(self.credentials_json) if isinstance(self.credentials_json, str) else self.credentials_json
            creds = Credentials.from_service_account_info(
                creds_data,
                scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
            )
            return gspread.authorize(creds)
        else:
            # Public sheet via anonymous access
            return gspread.Client(auth=None)

    def _open_sheet(self):
        gc = self._get_client()
        if self.spreadsheet_url.startswith("http"):
            return gc.open_by_url(self.spreadsheet_url)
        return gc.open_by_key(self.spreadsheet_url)

    def test_connection(self) -> tuple[str, str]:
        try:
            sheet = self._open_sheet()
            return "connected", f"Connected to '{sheet.title}' ({len(sheet.worksheets())} worksheets)"
        except Exception as e:
            return "error", f"Connection failed: {type(e).__name__}: {e}"

    def fetch_tables(self) -> List[str]:
        sheet = self._open_sheet()
        return [ws.title for ws in sheet.worksheets()]

    def fetch_schema(self, table: str) -> List[dict]:
        sheet = self._open_sheet()
        ws = sheet.worksheet(table)
        headers = ws.row_values(1)
        return [{"name": h, "type": "TEXT", "nullable": True} for h in headers if h]

    def extract_data(self, table_or_query: str, *, limit: Optional[int] = None) -> pd.DataFrame:
        sheet = self._open_sheet()
        ws = sheet.worksheet(table_or_query)
        data = ws.get_all_records()
        df = pd.DataFrame(data)
        if limit:
            df = df.head(limit)
        return df
