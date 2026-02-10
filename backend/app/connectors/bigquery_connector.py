"""Google BigQuery data connector (optional dependency)."""
from __future__ import annotations

import logging
from typing import List, Optional

import pandas as pd

from app.connectors.base import BaseConnector

logger = logging.getLogger(__name__)


class BigQueryConnector(BaseConnector):
    connector_type = "bigquery"

    def __init__(self, config: dict):
        super().__init__(config)
        self.project = config.get("project")
        self.dataset = config.get("dataset")
        self.credentials_json = config.get("credentials_json")

    def _get_client(self):
        try:
            from google.cloud import bigquery
        except ImportError:
            raise RuntimeError("Install 'google-cloud-bigquery' to use BigQuery connector: pip install google-cloud-bigquery")
        if self.credentials_json:
            import json
            from google.oauth2.service_account import Credentials
            creds_data = json.loads(self.credentials_json) if isinstance(self.credentials_json, str) else self.credentials_json
            creds = Credentials.from_service_account_info(creds_data)
            return bigquery.Client(project=self.project, credentials=creds)
        return bigquery.Client(project=self.project)

    def test_connection(self) -> tuple[str, str]:
        try:
            client = self._get_client()
            datasets = list(client.list_datasets(max_results=1))
            return "connected", f"BigQuery connection successful (project: {self.project})"
        except Exception as e:
            return "error", f"Connection failed: {type(e).__name__}: {e}"

    def fetch_tables(self) -> List[str]:
        client = self._get_client()
        tables = client.list_tables(f"{self.project}.{self.dataset}")
        return [t.table_id for t in tables]

    def fetch_schema(self, table: str) -> List[dict]:
        client = self._get_client()
        tbl = client.get_table(f"{self.project}.{self.dataset}.{table}")
        return [
            {"name": f.name, "type": f.field_type, "nullable": f.mode != "REQUIRED"}
            for f in tbl.schema
        ]

    def extract_data(self, table_or_query: str, *, limit: Optional[int] = None) -> pd.DataFrame:
        client = self._get_client()
        q = table_or_query.strip()
        if q.upper().startswith("SELECT"):
            sql = q
        else:
            sql = f"SELECT * FROM `{self.project}.{self.dataset}.{q}`"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return client.query(sql).to_dataframe()
