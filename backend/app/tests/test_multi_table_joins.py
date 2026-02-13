"""Tests for multi-table JOIN support.

Validates that:
- Plugin loader correctly parses relationships from schema.yaml
- SQL guard allows JOIN queries referencing multiple allowed tables
- SchemaContext generates prompt text that includes relationship info
- Backward compatibility: plugins without relationships still load correctly
"""

import yaml
import pytest

from app.plugin_loader import (
    PluginConfig,
    PluginManager,
    RelationshipDefinition,
)
from app.sql_guard import SQLGuard, SQLGuardError


def _write_yaml(path, data):
    path.write_text(yaml.safe_dump(data))


def _make_multi_table_plugin(tmp_path):
    """Creates a plugin with two tables and a relationship."""
    plugin_dir = tmp_path / "restaurant"
    plugin_dir.mkdir()

    schema = {
        "tables": {
            "sales_transactions": {
                "description": "Sales data",
                "primary_time_column": "order_datetime",
                "columns": {
                    "order_id": {"type": "string", "meaning": "Order ID", "nullable": False},
                    "order_datetime": {"type": "timestamp", "meaning": "Order time", "nullable": False},
                    "item_name": {"type": "string", "meaning": "Item name", "nullable": False},
                    "total_line_amount": {"type": "numeric", "meaning": "Total", "nullable": False},
                    "customer_id": {"type": "string", "meaning": "FK to customers", "nullable": True},
                },
            },
            "customers": {
                "description": "Customer records",
                "columns": {
                    "customer_id": {"type": "string", "meaning": "Customer ID", "nullable": False},
                    "customer_name": {"type": "string", "meaning": "Name", "nullable": False},
                    "loyalty_tier": {"type": "string", "meaning": "Tier", "nullable": True},
                },
            },
        },
        "relationships": [
            {
                "name": "sales_to_customer",
                "from_table": "sales_transactions",
                "from_column": "customer_id",
                "to_table": "customers",
                "to_column": "customer_id",
                "type": "many_to_one",
                "description": "Each sale may be linked to a customer",
            }
        ],
    }

    _write_yaml(plugin_dir / "schema.yaml", schema)
    _write_yaml(plugin_dir / "metrics.yaml", {"metrics": {}})
    _write_yaml(plugin_dir / "questions.yaml", {"question_packs": {}})
    _write_yaml(plugin_dir / "policy.yaml", {"allowed_question_types": [], "forbidden_topics": []})
    _write_yaml(plugin_dir / "insights.yaml", {"insights": {}})

    return tmp_path


# ── Plugin Loader: relationships parsing ──────────────────────────────────


def test_plugin_loads_relationships(tmp_path):
    """Plugin loader parses the relationships section from schema.yaml."""
    base = _make_multi_table_plugin(tmp_path)
    plugin = PluginConfig("restaurant", str(base))

    assert plugin.validated is True
    assert len(plugin.relationships) == 1

    rel = plugin.relationships[0]
    assert isinstance(rel, RelationshipDefinition)
    assert rel.name == "sales_to_customer"
    assert rel.from_table == "sales_transactions"
    assert rel.from_column == "customer_id"
    assert rel.to_table == "customers"
    assert rel.to_column == "customer_id"
    assert rel.relationship_type == "many_to_one"


def test_plugin_without_relationships_still_loads(tmp_path):
    """Backward compat: a plugin without relationships loads with empty list."""
    plugin_dir = tmp_path / "simple"
    plugin_dir.mkdir()
    _write_yaml(
        plugin_dir / "schema.yaml",
        {"tables": {"orders": {"columns": {"order_id": {"type": "string", "nullable": False}}}}},
    )
    _write_yaml(plugin_dir / "metrics.yaml", {"metrics": {}})
    _write_yaml(plugin_dir / "questions.yaml", {"question_packs": {}})
    _write_yaml(plugin_dir / "policy.yaml", {"allowed_question_types": [], "forbidden_topics": []})
    _write_yaml(plugin_dir / "insights.yaml", {"insights": {}})

    plugin = PluginConfig("simple", str(tmp_path))
    assert plugin.validated is True
    assert plugin.relationships == []


def test_plugin_multiple_relationships(tmp_path):
    """Plugin can define multiple relationships."""
    plugin_dir = tmp_path / "multi"
    plugin_dir.mkdir()
    schema = {
        "tables": {
            "orders": {"columns": {"id": {"type": "string"}, "customer_id": {"type": "string"}, "product_id": {"type": "string"}}},
            "customers": {"columns": {"customer_id": {"type": "string"}}},
            "products": {"columns": {"product_id": {"type": "string"}}},
        },
        "relationships": [
            {"name": "orders_to_customers", "from_table": "orders", "from_column": "customer_id", "to_table": "customers", "to_column": "customer_id", "type": "many_to_one"},
            {"name": "orders_to_products", "from_table": "orders", "from_column": "product_id", "to_table": "products", "to_column": "product_id", "type": "many_to_one"},
        ],
    }
    _write_yaml(plugin_dir / "schema.yaml", schema)
    _write_yaml(plugin_dir / "metrics.yaml", {"metrics": {}})
    _write_yaml(plugin_dir / "questions.yaml", {"question_packs": {}})
    _write_yaml(plugin_dir / "policy.yaml", {"allowed_question_types": [], "forbidden_topics": []})
    _write_yaml(plugin_dir / "insights.yaml", {"insights": {}})

    plugin = PluginConfig("multi", str(tmp_path))
    assert len(plugin.relationships) == 2
    assert plugin.relationships[0].name == "orders_to_customers"
    assert plugin.relationships[1].name == "orders_to_products"


def test_get_allowed_tables_includes_all_tables(tmp_path):
    """get_allowed_tables returns all tables including related ones."""
    base = _make_multi_table_plugin(tmp_path)
    plugin = PluginConfig("restaurant", str(base))

    allowed = plugin.get_allowed_tables()
    assert "sales_transactions" in allowed
    assert "customers" in allowed


def test_get_allowed_columns_includes_all_columns(tmp_path):
    """get_allowed_columns returns columns from all tables."""
    base = _make_multi_table_plugin(tmp_path)
    plugin = PluginConfig("restaurant", str(base))

    allowed = plugin.get_allowed_columns()
    # From sales_transactions
    assert "order_id" in allowed
    assert "total_line_amount" in allowed
    # From customers
    assert "customer_name" in allowed
    assert "loyalty_tier" in allowed


def test_to_dict_includes_relationships(tmp_path):
    """to_dict() output includes relationships."""
    base = _make_multi_table_plugin(tmp_path)
    plugin = PluginConfig("restaurant", str(base))

    d = plugin.to_dict()
    assert "relationships" in d
    assert len(d["relationships"]) == 1
    assert d["relationships"][0]["name"] == "sales_to_customer"


# ── Relationships description ─────────────────────────────────────────────


def test_get_relationships_description(tmp_path):
    """get_relationships_description returns JOIN guidance text."""
    base = _make_multi_table_plugin(tmp_path)
    plugin = PluginConfig("restaurant", str(base))

    desc = plugin.get_relationships_description()
    assert "sales_transactions" in desc
    assert "customers" in desc
    assert "customer_id" in desc
    assert "LEFT JOIN" in desc
    assert "many_to_one" in desc


def test_get_relationships_description_empty_when_no_relationships(tmp_path):
    """get_relationships_description returns empty string when no relationships."""
    plugin_dir = tmp_path / "norefs"
    plugin_dir.mkdir()
    _write_yaml(
        plugin_dir / "schema.yaml",
        {"tables": {"t": {"columns": {"id": {"type": "string"}}}}},
    )
    _write_yaml(plugin_dir / "metrics.yaml", {"metrics": {}})
    _write_yaml(plugin_dir / "questions.yaml", {"question_packs": {}})
    _write_yaml(plugin_dir / "policy.yaml", {"allowed_question_types": [], "forbidden_topics": []})
    _write_yaml(plugin_dir / "insights.yaml", {"insights": {}})

    plugin = PluginConfig("norefs", str(tmp_path))
    assert plugin.get_relationships_description() == ""


def test_schema_description_includes_relationships(tmp_path):
    """get_schema_description includes relationships section."""
    base = _make_multi_table_plugin(tmp_path)
    plugin = PluginConfig("restaurant", str(base))

    desc = plugin.get_schema_description()
    assert "Table Relationships" in desc
    assert "JOIN" in desc


# ── SQL Guard: JOIN queries ───────────────────────────────────────────────


def test_sql_guard_allows_simple_join():
    """SQL guard allows a basic JOIN query with allowed tables and columns."""
    guard = SQLGuard(
        {"sales_transactions", "customers"},
        {"order_id", "total_line_amount", "customer_id", "customer_name", "loyalty_tier"},
    )
    sql = (
        "SELECT c.customer_name, SUM(s.total_line_amount) AS total_spent "
        "FROM sales_transactions s "
        "LEFT JOIN customers c ON s.customer_id = c.customer_id "
        "GROUP BY c.customer_name "
        "ORDER BY total_spent DESC LIMIT 10"
    )
    assert guard.validate(sql) is True


def test_sql_guard_allows_inner_join():
    """SQL guard allows INNER JOIN."""
    guard = SQLGuard(
        {"production_runs", "quality_checks"},
        {"run_id", "units_produced", "check_id", "pass_fail", "check_type"},
    )
    sql = (
        "SELECT pr.run_id, pr.units_produced, qc.pass_fail "
        "FROM production_runs pr "
        "INNER JOIN quality_checks qc ON pr.run_id = qc.run_id "
        "LIMIT 20"
    )
    assert guard.validate(sql) is True


def test_sql_guard_allows_multi_join():
    """SQL guard allows queries that JOIN three tables."""
    guard = SQLGuard(
        {"sales_transactions", "products", "stores"},
        {"transaction_id", "sku", "store_id", "brand", "store_name", "total_amount"},
    )
    sql = (
        "SELECT st.store_name, p.brand, SUM(s.total_amount) AS revenue "
        "FROM sales_transactions s "
        "LEFT JOIN products p ON s.sku = p.sku "
        "LEFT JOIN stores st ON s.store_id = st.store_id "
        "GROUP BY st.store_name, p.brand "
        "ORDER BY revenue DESC LIMIT 10"
    )
    assert guard.validate(sql) is True


def test_sql_guard_blocks_unknown_table_in_join():
    """SQL guard rejects JOINs with tables not in the allowlist."""
    guard = SQLGuard(
        {"sales_transactions"},
        {"order_id", "total_line_amount", "customer_id"},
    )
    sql = (
        "SELECT * FROM sales_transactions s "
        "JOIN secret_table x ON s.customer_id = x.customer_id"
    )
    with pytest.raises(SQLGuardError):
        guard.validate(sql)


# ── SchemaContext: prompt generation (conditional import) ─────────────────


def test_schema_context_prompt_includes_relationships(tmp_path):
    """SchemaContext.to_prompt_string includes relationship guidance."""
    try:
        from app.llm_service import SchemaContext
    except BaseException:
        pytest.skip("llm_service not importable in this environment")

    base = _make_multi_table_plugin(tmp_path)
    plugin = PluginConfig("restaurant", str(base))

    ctx = SchemaContext(
        schema=plugin.schema,
        allowed_tables=plugin.get_allowed_tables(),
        allowed_columns=plugin.get_allowed_columns(),
        plugin_name=plugin.plugin_name,
        metrics_description=plugin.get_metrics_description(),
        views=[],
        relationships_description=plugin.get_relationships_description(),
        schema_description=plugin.get_schema_description(),
    )
    prompt = ctx.to_prompt_string()

    # Should include table schema info
    assert "sales_transactions" in prompt
    assert "customers" in prompt
    # Should include relationship guidance
    assert "customer_id" in prompt
    assert "JOIN" in prompt


def test_schema_context_prompt_without_relationships():
    """SchemaContext works fine with no relationships (backward compat)."""
    try:
        from app.llm_service import SchemaContext
    except BaseException:
        pytest.skip("llm_service not importable in this environment")

    ctx = SchemaContext(
        schema={},
        allowed_tables={"orders"},
        allowed_columns={"order_id"},
        plugin_name="test",
        metrics_description="",
        views=["v_test__metric"],
    )
    prompt = ctx.to_prompt_string()
    assert "v_test__metric" in prompt
    # No relationship section
    assert "Table Relationships" not in prompt


# ── Real plugin loading from plugins/ directory ───────────────────────────


def test_restaurant_plugin_has_relationships():
    """The real restaurant plugin has relationships defined."""
    try:
        plugin = PluginConfig("restaurant", "plugins")
    except Exception:
        pytest.skip("Restaurant plugin not available in test environment")

    assert len(plugin.relationships) >= 3
    rel_names = {r.name for r in plugin.relationships}
    assert "sales_to_menu" in rel_names
    assert "sales_to_customer" in rel_names
    assert "sales_to_staff" in rel_names

    # All referenced tables should be in schema
    for rel in plugin.relationships:
        assert rel.from_table in plugin.schema, f"from_table {rel.from_table} not in schema"
        assert rel.to_table in plugin.schema, f"to_table {rel.to_table} not in schema"


def test_retail_plugin_has_relationships():
    """The real retail plugin has relationships defined."""
    try:
        plugin = PluginConfig("retail", "plugins")
    except Exception:
        pytest.skip("Retail plugin not available in test environment")

    assert len(plugin.relationships) >= 3
    rel_names = {r.name for r in plugin.relationships}
    assert "sales_to_product" in rel_names
    assert "sales_to_store" in rel_names
    assert "sales_to_customer" in rel_names


def test_manufacturing_plugin_has_relationships():
    """The real manufacturing plugin has relationships defined."""
    try:
        plugin = PluginConfig("manufacturing", "plugins")
    except Exception:
        pytest.skip("Manufacturing plugin not available in test environment")

    assert len(plugin.relationships) >= 2
    rel_names = {r.name for r in plugin.relationships}
    assert "runs_to_quality" in rel_names
    assert "runs_to_machine" in rel_names
