import logging
import re
from dataclasses import dataclass
from typing import List, Dict
from pathlib import Path
import yaml

from app.plugin_loader import PluginConfig

logger = logging.getLogger(__name__)


@dataclass
class MetricDefinitionModel:
    id: str
    description: str
    sql: str  # normalized SQL (SELECT only)


@dataclass
class MetricCompileResult:
    metric_id: str
    view_name: str
    sql: str


def view_name(plugin_id: str, metric_id: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", metric_id)
    return f"v_{plugin_id}__{safe}"


def _inject_dataset(sql: str) -> str:
    sql_lower = sql.lower()
    if "dataset_id" in sql_lower:
        return sql
    # naive inject: add dataset_id to select list and group by if present
    match = re.search(r"select\s+(.*?)\s+from\s", sql, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return sql
    columns = match.group(1).strip()
    new_columns = f"dataset_id, {columns}"
    sql = re.sub(r"select\s+.*?\s+from\s", f"SELECT {new_columns} FROM ", sql, flags=re.IGNORECASE | re.DOTALL)
    if "group by" in sql_lower:
        sql = re.sub(r"group by\s+", "GROUP BY dataset_id, ", sql, flags=re.IGNORECASE)
    else:
        sql += " GROUP BY dataset_id"
    return sql


def load_metric_definitions(plugin: PluginConfig, metrics_path: Path) -> List[MetricDefinitionModel]:
    with open(metrics_path, "r") as f:
        data = yaml.safe_load(f) or {}
    metrics = data.get("metrics") or {}
    definitions: List[MetricDefinitionModel] = []
    for metric_id, metric_data in metrics.items():
        sql_template = metric_data.get("sql_template") or metric_data.get("sql")
        if not sql_template:
            continue
        sql = sql_template.replace("{table}", list(plugin.schema.keys())[0])
        sql = sql.replace("{time_filter}", "")
        definitions.append(
            MetricDefinitionModel(
                id=metric_id,
                description=metric_data.get("description", ""),
                sql=sql.strip(),
            )
        )
    return definitions


def compile_metrics(plugin: PluginConfig) -> List[MetricCompileResult]:
    metrics_file = plugin.config_dir / "metrics.yaml"
    if not metrics_file.exists():
        return []
    definitions = load_metric_definitions(plugin, metrics_file)
    compiled: List[MetricCompileResult] = []
    for metric in definitions:
        if not metric.sql.lower().startswith("select"):
            raise ValueError(f"{plugin.plugin_name}:{metric.id} metric SQL must be SELECT")
        sql = _inject_dataset(metric.sql)
        vname = view_name(plugin.plugin_name, metric.id)
        view_sql = f"CREATE OR REPLACE VIEW {vname} AS {sql};"
        compiled.append(MetricCompileResult(metric_id=metric.id, view_name=vname, sql=view_sql))
    return compiled
