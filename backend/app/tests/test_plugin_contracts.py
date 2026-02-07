import os
import json
from pathlib import Path
import pandas as pd
import pytest
from sqlalchemy import text

from app.plugins.validator import validate_plugin, list_plugin_paths, PluginValidationError
from app.sql_guard import SQLGuard, SQLGuardError
from app.metrics.compiler import compile_metrics
from app.main import Base


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PLUGINS_ROOT = PROJECT_ROOT / "plugins"
SAMPLE_ROOT = PROJECT_ROOT / "sample_data"


def type_sql(col_type: str) -> str:
    col_type = (col_type or "").lower()
    if "time" in col_type or "date" in col_type:
        return "timestamp"
    if "int" in col_type or "numeric" in col_type or "number" in col_type:
        return "numeric"
    return "text"


def ensure_tables(schema: dict, engine):
    with engine.begin() as conn:
        for table_name, table_def in schema["tables"].items():
            conn.execute(text(f"DROP TABLE IF EXISTS {table_name} CASCADE"))
            cols = ["dataset_id uuid"]
            for col_name, col_def in table_def.get("columns", {}).items():
                cols.append(f"{col_name} {type_sql(col_def.get('type'))}")
            stmt = f'CREATE TABLE IF NOT EXISTS {table_name} ({", ".join(cols)});'
            conn.execute(text(stmt))


def ingest_sample(plugin_id: str, schema: dict, engine):
    plugin_sample_dir = SAMPLE_ROOT / plugin_id
    if not plugin_sample_dir.exists():
        pytest.fail(f"{plugin_id}: sample data directory missing at {plugin_sample_dir}")
    csvs = list(plugin_sample_dir.glob("*.csv"))
    if not csvs:
        pytest.fail(f"{plugin_id}: no sample CSV files found in {plugin_sample_dir}")
    target_table = next(iter(schema["tables"].keys()))
    df = pd.read_csv(csvs[0])
    required_cols = []
    for col_name, col_def in schema["tables"][target_table].get("columns", {}).items():
        if col_def.get("nullable") is False:
            required_cols.append(col_name)
    if not required_cols:
        required_cols = list(schema["tables"][target_table].get("columns", {}).keys())
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        pytest.fail(f"{plugin_id}: sample CSV missing required columns {missing}")
    df["dataset_id"] = "00000000-0000-0000-0000-000000000000"
    df.to_sql(target_table, engine, if_exists="append", index=False)
    assert len(df) > 0, f"{plugin_id}: sample ingestion inserted zero rows"
    with engine.begin() as conn:
        count = conn.execute(text(f"SELECT count(*) FROM {target_table}")).scalar()
        assert count >= len(df), f"{plugin_id}: row count mismatch after ingestion"


def render_metric_sql(metric_sql: str, table: str) -> str:
    sql = metric_sql.replace("{table}", table)
    sql = sql.replace("{time_filter}", "")
    return sql


def explain(sql: str, engine):
    with engine.begin() as conn:
        conn.execute(text("EXPLAIN " + sql))


def test_all_plugins_contracts(db_session, engine):
    plugin_paths = list_plugin_paths(PLUGINS_ROOT)
    assert plugin_paths, "No plugins found to validate"
    for path in plugin_paths:
        plugin_id = path.name
        try:
            definition = validate_plugin(path)
        except PluginValidationError as e:
            pytest.fail(str(e))

        from app.plugin_loader import PluginConfig
        plugin_cfg = PluginConfig(plugin_id, str(path.parent))

        schema_dict = {
            "tables": {
                tname: {
                    "columns": {
                        cname: {"type": cdef.type, "nullable": cdef.nullable}
                        for cname, cdef in tdef.columns.items()
                    },
                    "primary_time_column": tdef.primary_time_column,
                }
                for tname, tdef in definition.tables.items()
            }
        }

        ensure_tables(schema_dict, engine)
        ingest_sample(plugin_id, schema_dict, engine)

        compiled = compile_metrics(plugin_cfg)
        allowed_tables = {c.view_name for c in compiled} if compiled else {t.lower() for t in definition.tables.keys()}
        allowed_cols = {"dataset_id"}
        for t in definition.tables.values():
            allowed_cols.update({c.lower() for c in t.columns.keys()})
        guard = SQLGuard(allowed_tables, allowed_cols)

        # metrics (views)
        for c in compiled:
            assert c.sql.lower().startswith("create or replace view"), f"{plugin_id}:{c.metric_id} view not created"
            body = c.sql.split("AS", 1)[1]
            guard.validate(body)
            explain(body, engine)

        # questions -> simple generated SQL (placeholder)
        for pack in definition.question_packs.values():
            # use pack description or patterns as examples
            example_sql = f"SELECT * FROM {next(iter(definition.tables.keys()))} LIMIT 1"
            guard.validate(example_sql)
            explain(example_sql, engine)

        # insights if any
        if hasattr(definition, "question_packs"):
            pass  # already handled

    # restore core tables for other tests
    Base.metadata.create_all(engine)
