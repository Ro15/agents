"""
Redis Result Cache — Task 5.1
Fast result caching with smart TTL based on data freshness.
Falls back gracefully to no-op if Redis is unavailable.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

_REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# TTL strategies by data type (seconds)
TTL_STATIC_FILE = 86400       # 24 hours — uploaded files don't change
TTL_AGGREGATE = 1800          # 30 minutes — SUM/COUNT queries
TTL_CONNECTOR_FAST = 300      # 5 minutes — connectors synced < 1h ago
TTL_CONNECTOR_SLOW = 3600     # 1 hour — connectors synced > 1h ago
TTL_DEFAULT = 3600            # 1 hour default


def _get_redis():
    """Get Redis client, returns None if unavailable."""
    try:
        import redis
        client = redis.from_url(_REDIS_URL, socket_connect_timeout=2, socket_timeout=2)
        client.ping()
        return client
    except Exception as e:
        logger.debug(f"Redis unavailable: {e}")
        return None


class ResultCache:
    """
    Redis-backed result cache with TTL management.
    Key structure: result:{plugin_id}:{dataset_id}:{sql_hash}
    """

    def __init__(self):
        self._client = None
        self._available = None

    def _get_client(self):
        if self._available is False:
            return None
        if self._client is None:
            self._client = _get_redis()
            self._available = self._client is not None
        return self._client

    def get(self, plugin_id: str, dataset_id: str, sql_hash: str) -> Optional[dict]:
        """Return cached result dict or None."""
        client = self._get_client()
        if client is None:
            return None
        try:
            from app.circuit_breaker import REDIS_BREAKER
            key = self._key(plugin_id, dataset_id, sql_hash)
            raw = REDIS_BREAKER.call(client.get, key)
            if raw is None:
                return None
            data = json.loads(raw)
            data["cache_hit"] = True
            return data
        except Exception as e:
            logger.debug(f"Cache get failed: {e}")
            return None

    def set(
        self,
        plugin_id: str,
        dataset_id: str,
        sql_hash: str,
        result: dict,
        ttl: int = TTL_DEFAULT,
    ) -> bool:
        """Store result in cache with TTL."""
        client = self._get_client()
        if client is None:
            return False
        try:
            from app.circuit_breaker import REDIS_BREAKER
            key = self._key(plugin_id, dataset_id, sql_hash)
            payload = json.dumps(result, default=str)
            REDIS_BREAKER.call(client.setex, key, ttl, payload)
            return True
        except Exception as e:
            logger.debug(f"Cache set failed: {e}")
            return False

    def invalidate_dataset(self, dataset_id: str) -> int:
        """Remove all cache entries for a dataset (after upload/delete)."""
        client = self._get_client()
        if client is None:
            return 0
        try:
            from app.circuit_breaker import REDIS_BREAKER
            pattern = f"result:*:{dataset_id}:*"
            keys = REDIS_BREAKER.call(client.keys, pattern)
            if keys:
                return REDIS_BREAKER.call(client.delete, *keys)
            return 0
        except Exception as e:
            logger.debug(f"Cache invalidation failed: {e}")
            return 0

    def invalidate_plugin(self, plugin_id: str) -> int:
        """Remove all cache entries for a plugin."""
        client = self._get_client()
        if client is None:
            return 0
        try:
            from app.circuit_breaker import REDIS_BREAKER
            pattern = f"result:{plugin_id}:*"
            keys = REDIS_BREAKER.call(client.keys, pattern)
            if keys:
                return REDIS_BREAKER.call(client.delete, *keys)
            return 0
        except Exception as e:
            logger.debug(f"Cache invalidation failed: {e}")
            return 0

    def get_stats(self) -> dict:
        """Return cache statistics."""
        client = self._get_client()
        if client is None:
            return {"available": False}
        try:
            from app.circuit_breaker import REDIS_BREAKER
            info = REDIS_BREAKER.call(client.info, "stats")
            return {
                "available": True,
                "keyspace_hits": info.get("keyspace_hits", 0),
                "keyspace_misses": info.get("keyspace_misses", 0),
                "hit_rate": (
                    info.get("keyspace_hits", 0) /
                    max(1, info.get("keyspace_hits", 0) + info.get("keyspace_misses", 0))
                ),
            }
        except Exception:
            return {"available": True, "error": "stats_unavailable"}

    @staticmethod
    def _key(plugin_id: str, dataset_id: str, sql_hash: str) -> str:
        return f"result:{plugin_id}:{dataset_id}:{sql_hash}"

    def choose_ttl(self, schema_type: str, last_sync_ago_seconds: Optional[int] = None) -> int:
        """Select appropriate TTL based on dataset type."""
        if schema_type == "dynamic":
            return TTL_STATIC_FILE
        if last_sync_ago_seconds is not None:
            if last_sync_ago_seconds < 3600:
                return TTL_CONNECTOR_FAST
            return TTL_CONNECTOR_SLOW
        return TTL_DEFAULT


# Module-level singleton
_cache = ResultCache()


def cache_get(plugin_id: str, dataset_id: str, sql_hash: str) -> Optional[dict]:
    return _cache.get(plugin_id, dataset_id, sql_hash)


def cache_set(plugin_id: str, dataset_id: str, sql_hash: str, result: dict, ttl: int = TTL_DEFAULT) -> bool:
    return _cache.set(plugin_id, dataset_id, sql_hash, result, ttl)


def cache_invalidate_dataset(dataset_id: str) -> int:
    return _cache.invalidate_dataset(dataset_id)


def cache_invalidate_plugin(plugin_id: str) -> int:
    return _cache.invalidate_plugin(plugin_id)


def cache_stats() -> dict:
    return _cache.get_stats()


def choose_ttl(schema_type: str, last_sync_ago_seconds: Optional[int] = None) -> int:
    return _cache.choose_ttl(schema_type, last_sync_ago_seconds)
