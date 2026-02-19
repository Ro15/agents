import os
import importlib
from fastapi.testclient import TestClient

from app import nl_to_sql


def test_chat_endpoint_with_mock_llm(monkeypatch, tmp_path):
    db_path = tmp_path / "chat.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    # Reload main to pick up test database URL
    from app import main as main_module
    main = importlib.reload(main_module)

    def fake_generate_sql(_query: str, **_kwargs):
        return nl_to_sql.SQLGenerationResult(
            sql="SELECT 1 as value",
            answer_type="number",
            assumptions=[],
            confidence="high",
            intent="analytics_query",
            repairs=0,
            model_name="mock",
        )

    monkeypatch.setattr(main.nl_to_sql, "generate_sql", fake_generate_sql)

    client = TestClient(main.app)
    resp = client.post("/chat", json={"query": "test number", "plugin": "retail"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["answer_type"] == "number"
    assert data["confidence"] in {"high", "medium", "low"}
