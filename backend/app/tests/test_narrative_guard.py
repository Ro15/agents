from app.routes_core import _narrative_supported_by_answer


def test_narrative_claim_check_accepts_supported_number():
    answer = [{"metric": "revenue", "value": 1200.0}]
    assert _narrative_supported_by_answer("Revenue was 1200 this week.", answer, "table") is True


def test_narrative_claim_check_rejects_unsupported_number():
    answer = [{"metric": "revenue", "value": 1200.0}]
    assert _narrative_supported_by_answer("Revenue was 9999 this week.", answer, "table") is False
