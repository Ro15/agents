import uuid
from cache.cache import cache_get, cache_set, stable_hash
from app.nl_to_sql import SQLGenerationResult


def test_cache_set_get_roundtrip():
    cache_set("llm_sql", "k1", {"v": 1}, 5)
    assert cache_get("llm_sql", "k1") == {"v": 1}


def test_stable_hash_changes_on_dataset():
    h1 = stable_hash({"ds": "a"})
    h2 = stable_hash({"ds": "b"})
    assert h1 != h2
