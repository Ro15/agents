"""REST API data connector — pulls JSON data from HTTP endpoints."""
from __future__ import annotations

import logging
from typing import List, Optional

import pandas as pd

from app.connectors.base import BaseConnector

logger = logging.getLogger(__name__)


class RestAPIConnector(BaseConnector):
    connector_type = "api"

    def __init__(self, config: dict):
        super().__init__(config)
        self.base_url = config.get("url", "")
        self.headers = config.get("headers", {})
        self.auth_token = config.get("auth_token")
        self.data_path = config.get("data_path", "")  # JSONPath-like: "results.data"
        self.method = config.get("method", "GET").upper()

    def _request(self, url: str, params: dict = None) -> dict:
        import httpx
        headers = {**self.headers}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        with httpx.Client(timeout=30) as client:
            if self.method == "POST":
                resp = client.post(url, headers=headers, json=params or {})
            else:
                resp = client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            return resp.json()

    def _extract_data_from_json(self, data):
        """Navigate into nested JSON using dot-separated data_path."""
        if not self.data_path:
            return data
        for key in self.data_path.split("."):
            if isinstance(data, dict):
                data = data.get(key, data)
            elif isinstance(data, list) and key.isdigit():
                data = data[int(key)]
        return data

    def test_connection(self) -> tuple[str, str]:
        try:
            data = self._request(self.base_url)
            return "connected", f"API responded successfully (type: {type(data).__name__})"
        except Exception as e:
            return "error", f"Connection failed: {type(e).__name__}: {e}"

    def fetch_tables(self) -> List[str]:
        # REST APIs don't have "tables" — return the base endpoint
        return [self.base_url]

    def fetch_schema(self, table: str) -> List[dict]:
        data = self._request(table)
        rows = self._extract_data_from_json(data)
        if isinstance(rows, list) and len(rows) > 0 and isinstance(rows[0], dict):
            return [{"name": k, "type": "TEXT", "nullable": True} for k in rows[0].keys()]
        return []

    def extract_data(self, table_or_query: str, *, limit: Optional[int] = None) -> pd.DataFrame:
        url = table_or_query if table_or_query.startswith("http") else self.base_url
        data = self._request(url)
        rows = self._extract_data_from_json(data)
        if isinstance(rows, list):
            df = pd.json_normalize(rows)
        elif isinstance(rows, dict):
            df = pd.json_normalize([rows])
        else:
            raise ValueError(f"Expected list or dict, got {type(rows).__name__}")
        if limit:
            df = df.head(limit)
        return df
