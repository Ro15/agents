import pandas as pd
import pytest

from app.connectors.base import BaseConnector
from app.connectors.factory import CONNECTOR_REGISTRY, get_connector
from app.connectors.cloud_storage_connector import CloudStorageConnector
from app.connectors.rest_api_connector import RestAPIConnector
from app.connectors.mssql_connector import MSSQLConnector


EXPECTED_CONNECTOR_TYPES = {
    "postgresql",
    "mysql",
    "mssql",
    "bigquery",
    "snowflake",
    "sheets",
    "excel",
    "api",
    "s3",
    "gcs",
    "azure",
    "cloud_storage",
}


def test_connector_registry_has_all_expected_types():
    assert set(CONNECTOR_REGISTRY.keys()) == EXPECTED_CONNECTOR_TYPES


@pytest.mark.parametrize("connector_type", sorted(EXPECTED_CONNECTOR_TYPES))
def test_factory_builds_connector_instances(connector_type):
    connector = get_connector(connector_type, {})
    assert isinstance(connector, BaseConnector)


def test_factory_injects_provider_for_cloud_variants():
    for provider in ("s3", "gcs", "azure"):
        connector = get_connector(provider, {"bucket": "demo"})
        assert isinstance(connector, CloudStorageConnector)
        assert connector.provider == provider


def test_mssql_extract_data_uses_top_for_limit(monkeypatch):
    captured = {}

    def fake_read_sql(query, _engine):
        captured["query"] = query
        return pd.DataFrame([{"id": 1}])

    connector = MSSQLConnector({"url": "mssql://demo"})
    monkeypatch.setattr(connector, "_get_engine", lambda: object())
    monkeypatch.setattr(pd, "read_sql", fake_read_sql)

    df = connector.extract_data("orders", limit=10)

    assert not df.empty
    assert captured["query"].startswith("SELECT TOP 10")
    assert "FROM [orders]" in captured["query"]


def test_rest_api_connector_json_extraction_from_nested_path(monkeypatch):
    connector = RestAPIConnector(
        {
            "url": "https://example.com/orders",
            "data_path": "results.items",
        }
    )

    monkeypatch.setattr(
        connector,
        "_request",
        lambda *_args, **_kwargs: {"results": {"items": [{"id": 1, "name": "a"}]}},
    )

    status, message = connector.test_connection()
    assert status == "connected"
    assert "API responded successfully" in message

    schema = connector.fetch_schema(connector.base_url)
    assert {"name": "id", "type": "TEXT", "nullable": True} in schema

    df = connector.extract_data(connector.base_url)
    assert list(df.columns) == ["id", "name"]
    assert len(df) == 1


def test_cloud_storage_connector_extract_data_parses_supported_file(monkeypatch):
    connector = CloudStorageConnector({"provider": "s3", "bucket": "demo"})

    monkeypatch.setattr(connector, "_read_s3", lambda _key: b"id,name\n1,Alice\n2,Bob\n")

    df = connector.extract_data("customers.csv", limit=1)

    assert list(df.columns) == ["id", "name"]
    assert len(df) == 1
