import yaml
from app.plugin_loader import PluginManager


def _write_yaml(path, data):
    path.write_text(yaml.safe_dump(data))


def test_plugin_loader_valid_plugin(tmp_path):
    plugin_dir = tmp_path / "retail"
    plugin_dir.mkdir()
    _write_yaml(
        plugin_dir / "schema.yaml",
        {"tables": {"orders": {"columns": {"order_id": {"type": "string", "nullable": False}}}}},
    )
    _write_yaml(
        plugin_dir / "metrics.yaml",
        {"metrics": {"orders_count": {"description": "count orders", "sql_template": "SELECT count(*) FROM orders"}}},
    )
    _write_yaml(plugin_dir / "questions.yaml", {"question_packs": {}})
    _write_yaml(plugin_dir / "policy.yaml", {"allowed_question_types": [], "forbidden_topics": []})
    _write_yaml(plugin_dir / "insights.yaml", {"insights": {}})

    manager = PluginManager(str(tmp_path))
    assert "retail" in manager.plugins
    assert manager.plugins["retail"].validated is True


def test_plugin_loader_invalid_metric(tmp_path):
    plugin_dir = tmp_path / "bad"
    plugin_dir.mkdir()
    _write_yaml(
        plugin_dir / "schema.yaml",
        {"tables": {"orders": {"columns": {"order_id": {"type": "string", "nullable": False}}}}},
    )
    _write_yaml(
        plugin_dir / "metrics.yaml",
        {"metrics": {"bad": {"description": "bad", "sql_template": "SELECT * FROM missing_table"}}},
    )
    _write_yaml(plugin_dir / "questions.yaml", {"question_packs": {}})
    _write_yaml(plugin_dir / "policy.yaml", {"allowed_question_types": [], "forbidden_topics": []})
    _write_yaml(plugin_dir / "insights.yaml", {"insights": {}})

    manager = PluginManager(str(tmp_path))
    assert "bad" not in manager.plugins  # skipped due to validation errors
