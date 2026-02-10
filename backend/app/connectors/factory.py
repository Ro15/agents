"""
Connector factory — maps connector_type strings to connector classes.
"""

import logging
from typing import Dict, Type

from app.connectors.base import BaseConnector
from app.connectors.postgres_connector import PostgresConnector
from app.connectors.mysql_connector import MySQLConnector
from app.connectors.mssql_connector import MSSQLConnector
from app.connectors.sheets_connector import SheetsConnector
from app.connectors.rest_api_connector import RestAPIConnector
from app.connectors.excel_connector import ExcelConnector
from app.connectors.bigquery_connector import BigQueryConnector
from app.connectors.snowflake_connector import SnowflakeConnector
from app.connectors.cloud_storage_connector import CloudStorageConnector

logger = logging.getLogger(__name__)

CONNECTOR_REGISTRY: Dict[str, Type[BaseConnector]] = {
    "postgresql": PostgresConnector,
    "mysql": MySQLConnector,
    "mssql": MSSQLConnector,
    "sheets": SheetsConnector,
    "api": RestAPIConnector,
    "excel": ExcelConnector,
    "bigquery": BigQueryConnector,
    "snowflake": SnowflakeConnector,
    "s3": CloudStorageConnector,
    "gcs": CloudStorageConnector,
    "azure": CloudStorageConnector,
    "cloud_storage": CloudStorageConnector,
}


def get_connector(connector_type: str, config: dict) -> BaseConnector:
    """
    Instantiate a connector by type name.

    Raises ValueError if the type is unknown.
    """
    cls = CONNECTOR_REGISTRY.get(connector_type)
    if not cls:
        raise ValueError(
            f"Unknown connector type '{connector_type}'. "
            f"Available: {sorted(CONNECTOR_REGISTRY.keys())}"
        )
    # Inject provider for cloud storage variants
    if connector_type in ("s3", "gcs", "azure"):
        config = {**config, "provider": connector_type}
    return cls(config)
