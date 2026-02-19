import json
from pathlib import Path

from app import nl_to_sql


def test_golden_question_intents():
    golden_path = Path(__file__).with_name("golden_questions.json")
    data = json.loads(golden_path.read_text(encoding="utf-8"))
    assert data, "golden questions must not be empty"
    for item in data:
        question = item["question"]
        expected = item["expected_intent"]
        actual = nl_to_sql.classify_intent(question)
        assert actual == expected, f"intent mismatch for question='{question}'"
