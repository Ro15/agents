from types import SimpleNamespace

from app import nl_to_sql
from app.llm_service import LLMResponse


class _FakePlugin:
    plugin_name = "retail"
    schema = {}
    compiled_views = []
    compiled_view_sql = []
    policy = SimpleNamespace(max_date_range_days=None, forbidden_topics=[])

    def validate_question(self, _q):
        return True, ""

    def get_allowed_tables(self):
        return {"sales_transactions"}

    def get_allowed_columns(self):
        return {"order_datetime", "total_line_amount", "dataset_id"}

    def get_metrics_description(self):
        return ""

    def get_relationships_description(self):
        return ""

    def get_schema_description(self):
        return ""

    def primary_time_column(self):
        return "order_datetime"


class _FakeGuard:
    def validate(self, _sql):
        return True


def test_generate_sql_uses_cache_when_feedback_absent(monkeypatch):
    monkeypatch.setattr(nl_to_sql, "ACTIVE_PLUGIN", _FakePlugin())
    monkeypatch.setattr(nl_to_sql, "SQL_GUARD", _FakeGuard())

    cached_payload = {
        "sql": "SELECT 1",
        "answer_type": "number",
        "assumptions": [],
        "model_name": "cached-model",
        "chart_hint": "none",
        "summary": "cached",
    }
    monkeypatch.setattr(nl_to_sql, "cache_get", lambda *_args, **_kwargs: cached_payload)

    called = {"llm": False}

    def _never_called(**_kwargs):
        called["llm"] = True
        return None

    monkeypatch.setattr(nl_to_sql, "generate_sql_with_llm", _never_called)
    res = nl_to_sql.generate_sql("what is total sales", dataset_id="d1", dataset_version=1)
    assert res.sql == "SELECT 1"
    assert called["llm"] is False


def test_generate_sql_bypasses_cache_with_feedback_and_uses_env_timezone(monkeypatch):
    monkeypatch.setattr(nl_to_sql, "ACTIVE_PLUGIN", _FakePlugin())
    monkeypatch.setattr(nl_to_sql, "SQL_GUARD", _FakeGuard())
    monkeypatch.setenv("LLM_TIMEZONE", "America/New_York")

    # Should not be used when feedback is provided.
    monkeypatch.setattr(nl_to_sql, "cache_get", lambda *_args, **_kwargs: {
        "sql": "SELECT should_not_be_used",
        "answer_type": "table",
    })
    monkeypatch.setattr(nl_to_sql, "cache_set", lambda *_args, **_kwargs: None)

    captured = {"timezone": None}

    def _fake_llm(**kwargs):
        captured["timezone"] = kwargs.get("timezone")
        return LLMResponse(
            sql="SELECT total_line_amount FROM sales_transactions",
            answer_type="table",
            assumptions=[],
            model_name="test-model",
        )

    monkeypatch.setattr(nl_to_sql, "generate_sql_with_llm", _fake_llm)
    res = nl_to_sql.generate_sql(
        "what is total sales",
        dataset_id="d1",
        dataset_version=1,
        feedback={"error": "execution failed"},
    )
    assert "should_not_be_used" not in (res.sql or "")
    assert captured["timezone"] == "America/New_York"
    assert "LIMIT 200" in (res.sql or "")
