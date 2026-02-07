import pytest

from app.sql_guard import SQLGuard, SQLGuardError


def test_sql_guard_allows_selects():
    guard = SQLGuard({"orders"}, {"order_id", "amount"})
    sql = "SELECT order_id, amount FROM orders LIMIT 10"
    assert guard.validate(sql) is True


def test_sql_guard_blocks_unknown_identifier():
    guard = SQLGuard({"orders"}, {"order_id", "amount"})
    with pytest.raises(SQLGuardError):
        guard.validate("SELECT secret_column FROM orders")


def test_dataset_filter_injection_and_literal_block():
    guard = SQLGuard({"orders"}, {"order_id", "amount", "dataset_id"})
    # literal should fail
    with pytest.raises(SQLGuardError):
        guard.enforce_dataset_filter("SELECT * FROM orders WHERE dataset_id = 'abc'")
    scoped = guard.enforce_dataset_filter("SELECT * FROM orders", "dataset_id")
    assert "dataset_id" in scoped.lower()
