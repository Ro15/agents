"""
Base connector interface.
Every data source connector inherits from this class.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

import pandas as pd


class BaseConnector(ABC):
    """Abstract base class for all data connectors."""

    connector_type: str = "unknown"

    def __init__(self, config: dict):
        self.config = config or {}

    @abstractmethod
    def test_connection(self) -> tuple[str, str]:
        """
        Test that the connection is reachable.
        Returns (status, message) where status is "connected" or "error".
        """
        ...

    @abstractmethod
    def fetch_tables(self) -> List[str]:
        """List available tables / sheets / endpoints."""
        ...

    @abstractmethod
    def fetch_schema(self, table: str) -> List[dict]:
        """
        Return column definitions for a table.
        Each dict: {"name": str, "type": str, "nullable": bool}
        """
        ...

    @abstractmethod
    def extract_data(
        self,
        table_or_query: str,
        *,
        limit: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        Extract data into a DataFrame.
        `table_or_query` is a table name or SQL query (for DB connectors).
        """
        ...
