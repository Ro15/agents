"""Microsoft SQL Server data connector."""

from typing import Optional

import pandas as pd

from app.connectors.sqlalchemy_connector import SQLAlchemyConnector


class MSSQLConnector(SQLAlchemyConnector):
    connector_type = "mssql"
    _quote_char = '"'  # T-SQL also supports []

    def extract_data(self, table_or_query: str, *, limit: Optional[int] = None) -> pd.DataFrame:
        """Override to use TOP instead of LIMIT for T-SQL."""
        eng = self._get_engine()
        q = table_or_query.strip()
        if not q.upper().startswith("SELECT"):
            q = f'SELECT * FROM [{q}]'
        if limit:
            # Inject TOP into SELECT
            q = q.replace("SELECT", f"SELECT TOP {int(limit)}", 1)
        return pd.read_sql(q, eng)
