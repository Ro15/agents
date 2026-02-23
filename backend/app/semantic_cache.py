"""
Semantic Cache — Task 1.2
pgvector-based embedding similarity cache.

Uses the same embedding model as the RAG service (text-embedding-ada-002 or local).
Queries with cosine similarity >= THRESHOLD are considered cache hits.

Falls back silently if pgvector is not installed or embeddings are unavailable.

Schema (auto-created):
  semantic_query_cache(
    id          SERIAL PRIMARY KEY,
    plugin_id   TEXT,
    question    TEXT,
    embedding   vector(1536),
    sql_result  JSON,
    created_at  TIMESTAMPTZ DEFAULT now(),
    hits        INT DEFAULT 0,
  )

Requires:
  pip install pgvector
  CREATE EXTENSION IF NOT EXISTS vector;  -- in Postgres
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = float(os.getenv("SEMANTIC_CACHE_THRESHOLD", "0.94"))
MAX_CACHE_ROWS = int(os.getenv("SEMANTIC_CACHE_MAX_ROWS", "5000"))
_ENABLED = os.getenv("SEMANTIC_CACHE_ENABLED", "true").lower() in ("1", "true", "yes")

_TABLE_CREATED = False


def _ensure_table(conn) -> bool:
    """Create the semantic cache table + index if they don't exist. Returns False on error."""
    global _TABLE_CREATED
    if _TABLE_CREATED:
        return True
    try:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS semantic_query_cache (
                id         SERIAL PRIMARY KEY,
                plugin_id  TEXT NOT NULL,
                embedding  vector(1536) NOT NULL,
                question   TEXT,
                sql_result JSON,
                hits       INT NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_sem_cache_plugin
            ON semantic_query_cache (plugin_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_sem_cache_embedding
            ON semantic_query_cache USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100)
        """)
        conn.execute("COMMIT")
        _TABLE_CREATED = True
        return True
    except Exception as e:
        logger.debug(f"Semantic cache table setup skipped: {e}")
        return False


def _get_embedding(text: str) -> Optional[list[float]]:
    """Get embedding vector from OpenAI (or configured provider)."""
    try:
        import openai
        api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_API_BASE")
        if not api_key:
            return None

        client = openai.OpenAI(api_key=api_key, base_url=base_url)
        resp = client.embeddings.create(
            input=text,
            model=os.getenv("EMBEDDING_MODEL", "text-embedding-ada-002"),
        )
        return resp.data[0].embedding
    except Exception as e:
        logger.debug(f"Embedding generation failed: {e}")
        return None


def semantic_cache_get(engine, plugin_id: str, question: str) -> Optional[dict]:
    """
    Look up a semantically similar question in the cache.
    Returns the cached sql_result dict, or None on miss.
    """
    if not _ENABLED:
        return None
    try:
        embedding = _get_embedding(question)
        if embedding is None:
            return None

        vec_str = "[" + ",".join(str(x) for x in embedding) + "]"
        with engine.connect() as conn:
            if not _ensure_table(conn):
                return None

            result = conn.execute(f"""
                SELECT id, sql_result, 1 - (embedding <=> '{vec_str}') AS similarity
                FROM semantic_query_cache
                WHERE plugin_id = '{plugin_id}'
                ORDER BY embedding <=> '{vec_str}'
                LIMIT 1
            """).fetchone()

            if result is None:
                return None

            row_id, sql_result_json, similarity = result
            if similarity < SIMILARITY_THRESHOLD:
                return None

            # Increment hit counter
            conn.execute(f"UPDATE semantic_query_cache SET hits = hits + 1 WHERE id = {row_id}")
            conn.execute("COMMIT")

            logger.info(f"Semantic cache HIT (similarity={similarity:.3f}) for '{question[:60]}'")
            return json.loads(sql_result_json) if isinstance(sql_result_json, str) else sql_result_json

    except Exception as e:
        logger.debug(f"Semantic cache get failed: {e}")
        return None


def semantic_cache_set(engine, plugin_id: str, question: str, sql_result: dict) -> bool:
    """
    Store a question + result in the semantic cache.
    Evicts oldest rows if MAX_CACHE_ROWS is exceeded.
    Returns True on success.
    """
    if not _ENABLED:
        return False
    try:
        embedding = _get_embedding(question)
        if embedding is None:
            return False

        vec_str = "[" + ",".join(str(x) for x in embedding) + "]"
        result_json = json.dumps(sql_result, default=str)

        with engine.connect() as conn:
            if not _ensure_table(conn):
                return False

            conn.execute(f"""
                INSERT INTO semantic_query_cache (plugin_id, embedding, question, sql_result)
                VALUES ('{plugin_id}', '{vec_str}', $1, $2)
            """, (question, result_json))

            # Evict oldest rows if over limit
            conn.execute(f"""
                DELETE FROM semantic_query_cache
                WHERE id IN (
                    SELECT id FROM semantic_query_cache
                    ORDER BY created_at ASC
                    OFFSET {MAX_CACHE_ROWS}
                )
            """)
            conn.execute("COMMIT")
        return True
    except Exception as e:
        logger.debug(f"Semantic cache set failed: {e}")
        return False


def semantic_cache_invalidate(engine, plugin_id: str) -> int:
    """Remove all cache entries for a plugin. Returns count deleted."""
    try:
        with engine.connect() as conn:
            result = conn.execute(
                f"DELETE FROM semantic_query_cache WHERE plugin_id = '{plugin_id}' RETURNING id"
            ).fetchall()
            conn.execute("COMMIT")
            return len(result)
    except Exception as e:
        logger.debug(f"Semantic cache invalidate failed: {e}")
        return 0
