import os
import time
import json
import hashlib
import threading
from typing import Any, Optional, Dict


CACHE_ENABLED = os.getenv("CACHE_ENABLED", "true").lower() != "false"
LLM_SQL_CACHE_TTL_SECONDS = int(os.getenv("LLM_SQL_CACHE_TTL_SECONDS", "21600"))  # 6h
DB_RESULT_CACHE_TTL_SECONDS = int(os.getenv("DB_RESULT_CACHE_TTL_SECONDS", "120"))  # 2m


class _MemoryCache:
    def __init__(self):
        self.store: Dict[str, tuple[float, Any]] = {}
        self.lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        now = time.time()
        with self.lock:
            val = self.store.get(key)
            if not val:
                return None
            exp, data = val
            if exp < now:
                self.store.pop(key, None)
                return None
            return data

    def set(self, key: str, value: Any, ttl: int):
        exp = time.time() + ttl
        with self.lock:
            self.store[key] = (exp, value)


_memory_cache = _MemoryCache()


def stable_hash(obj: Any) -> str:
    txt = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(txt.encode("utf-8")).hexdigest()


def normalize_question(text: str) -> str:
    t = (text or "").lower().strip()
    t = " ".join(t.split())
    return t


def _namespaced_key(ns: str, key: str) -> str:
    return f"{ns}:{key}"


def cache_get(ns: str, key: str) -> Optional[Any]:
    if not CACHE_ENABLED:
        return None
    return _memory_cache.get(_namespaced_key(ns, key))


def cache_set(ns: str, key: str, value: Any, ttl_seconds: int):
    if not CACHE_ENABLED:
        return
    _memory_cache.set(_namespaced_key(ns, key), value, ttl_seconds)
