"""
Lightweight RAG utilities:
- Knowledge ingestion/chunking
- Retrieval (KB + examples + schema)
- Query rewrite
- Context reranking/packing
- Learning loop and review queue helpers
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID
from urllib import request as urlrequest

from sqlalchemy.orm import Session

from app import nl_to_sql
from app.llm_service import LLMConfig, generate_text_response
from app.models import (
    KnowledgeDocument,
    KnowledgeChunk,
    RAGExample,
    HumanReviewQueue,
    QueryFeedback,
)

logger = logging.getLogger(__name__)


STOP_WORDS = {
    "the", "a", "an", "to", "of", "in", "on", "for", "is", "are", "was", "were", "be", "as", "at",
    "from", "by", "with", "and", "or", "that", "this", "it", "show", "me", "what", "how", "when",
    "which", "who", "whom", "about", "into", "than", "then", "also", "now",
}


def tokenize_text(text_value: str) -> List[str]:
    tokens = [t for t in re.findall(r"[a-zA-Z][a-zA-Z0-9_]+", (text_value or "").lower()) if len(t) > 2]
    return [t for t in tokens if t not in STOP_WORDS]


def _chunk_text(text_value: str, chunk_size: int = 900, overlap: int = 120) -> List[str]:
    text_value = (text_value or "").strip()
    if not text_value:
        return []
    if len(text_value) <= chunk_size:
        return [text_value]
    chunks: List[str] = []
    pos = 0
    n = len(text_value)
    while pos < n:
        end = min(n, pos + chunk_size)
        chunk = text_value[pos:end]
        if end < n:
            # move end to nearest sentence/whitespace boundary
            boundary = max(chunk.rfind(". "), chunk.rfind("\n"), chunk.rfind(" "))
            if boundary > int(chunk_size * 0.5):
                end = pos + boundary + 1
                chunk = text_value[pos:end]
        chunks.append(chunk.strip())
        if end >= n:
            break
        pos = max(end - overlap, pos + 1)
    return [c for c in chunks if c]


def _sim_score(query_tokens: List[str], item_tokens: List[str], raw_text: str = "") -> float:
    if not query_tokens:
        return 0.0
    q = set(query_tokens)
    d = set(item_tokens or [])
    if not d:
        return 0.0
    overlap = q.intersection(d)
    score = len(overlap) / max(1, len(q))
    # boost phrase containment
    raw = (raw_text or "").lower()
    phrase_hits = 0
    for tok in list(q)[:8]:
        if tok in raw:
            phrase_hits += 1
    score += phrase_hits * 0.03
    return float(score)


def ingest_knowledge_document(
    db: Session,
    plugin_id: str,
    title: str,
    content: str,
    dataset_id: Optional[str] = None,
    source_type: str = "manual",
    source_uri: Optional[str] = None,
    metadata_json: Optional[dict] = None,
) -> KnowledgeDocument:
    if not (title or "").strip():
        raise ValueError("title is required")
    content = (content or "").strip()
    if not content and source_uri and source_uri.startswith(("http://", "https://")):
        try:
            timeout = float(os.getenv("RAG_URL_FETCH_TIMEOUT_SECONDS", "10"))
            with urlrequest.urlopen(source_uri, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            # very lightweight HTML stripping
            raw = re.sub(r"(?is)<script.*?>.*?</script>", " ", raw)
            raw = re.sub(r"(?is)<style.*?>.*?</style>", " ", raw)
            raw = re.sub(r"(?is)<[^>]+>", " ", raw)
            raw = re.sub(r"\s+", " ", raw).strip()
            content = raw
        except Exception as e:
            raise ValueError(f"failed_to_fetch_source_uri: {e}") from e
    if not content:
        raise ValueError("content is required (or provide fetchable source_uri)")
    doc = KnowledgeDocument(
        plugin_id=plugin_id,
        dataset_id=dataset_id,
        title=title.strip()[:255],
        source_type=(source_type or "manual").strip()[:32],
        source_uri=(source_uri or "").strip()[:1000] or None,
        content=content,
        metadata_json=metadata_json or {},
        updated_at=datetime.utcnow(),
    )
    db.add(doc)
    db.flush()

    chunk_size = int(os.getenv("RAG_CHUNK_SIZE", "900"))
    overlap = int(os.getenv("RAG_CHUNK_OVERLAP", "120"))
    chunks = _chunk_text(doc.content, chunk_size=chunk_size, overlap=overlap)
    for i, chunk in enumerate(chunks):
        tokens = tokenize_text(chunk)
        db.add(KnowledgeChunk(
            doc_id=doc.doc_id,
            plugin_id=plugin_id,
            dataset_id=dataset_id,
            chunk_index=i,
            content=chunk,
            token_set=tokens[:300],
            metadata_json={"title": doc.title, "source_type": doc.source_type},
        ))
    db.commit()
    db.refresh(doc)
    return doc


def retrieve_kb_chunks(
    db: Session,
    plugin_id: str,
    question: str,
    dataset_id: Optional[str] = None,
    limit: int = 8,
) -> List[Dict[str, Any]]:
    q = db.query(KnowledgeChunk).filter(KnowledgeChunk.plugin_id == plugin_id)
    if dataset_id:
        q = q.filter((KnowledgeChunk.dataset_id == dataset_id) | (KnowledgeChunk.dataset_id.is_(None)))
    rows = q.limit(1500).all()
    q_tokens = tokenize_text(question)
    scored: List[Tuple[float, KnowledgeChunk]] = []
    for row in rows:
        score = _sim_score(q_tokens, row.token_set or [], row.content)
        if score <= 0:
            continue
        scored.append((score, row))
    scored.sort(key=lambda x: x[0], reverse=True)
    out: List[Dict[str, Any]] = []
    for score, row in scored[:limit]:
        title = ""
        if isinstance(row.metadata_json, dict):
            title = row.metadata_json.get("title", "")
        out.append({
            "source_type": "kb_chunk",
            "id": str(row.chunk_id),
            "score": round(score, 4),
            "title": title,
            "snippet": row.content[:500],
            "metadata": row.metadata_json or {},
        })
    return out


def retrieve_schema_snippets(
    plugin,
    question: str,
    dynamic_columns: Optional[List[Dict[str, Any]]] = None,
    dynamic_table: Optional[str] = None,
    limit: int = 8,
) -> List[Dict[str, Any]]:
    q_tokens = tokenize_text(question)
    items: List[Dict[str, Any]] = []
    if dynamic_columns and dynamic_table:
        for col in dynamic_columns:
            col_name = col.get("column_name") or col.get("name") or ""
            desc = col.get("description") or ""
            dtype = col.get("data_type") or col.get("type") or ""
            text_blob = f"{dynamic_table} {col_name} {desc} {dtype}"
            score = _sim_score(q_tokens, tokenize_text(text_blob), text_blob)
            if score <= 0:
                continue
            items.append({
                "source_type": "schema",
                "id": f"{dynamic_table}.{col_name}",
                "score": round(score, 4),
                "title": f"{dynamic_table}.{col_name}",
                "snippet": f"{dynamic_table}.{col_name} ({dtype}) - {desc}".strip(),
                "metadata": {"table": dynamic_table, "column": col_name, "dtype": dtype},
            })
    else:
        for table_name, table in plugin.schema.items():
            for col_name, col in table.columns.items():
                text_blob = f"{table_name} {col_name} {col.type} {col.meaning}"
                score = _sim_score(q_tokens, tokenize_text(text_blob), text_blob)
                if score <= 0:
                    continue
                items.append({
                    "source_type": "schema",
                    "id": f"{table_name}.{col_name}",
                    "score": round(score, 4),
                    "title": f"{table_name}.{col_name}",
                    "snippet": f"{table_name}.{col_name} ({col.type}) - {col.meaning}".strip(),
                    "metadata": {"table": table_name, "column": col_name, "dtype": col.type},
                })
    items.sort(key=lambda x: x["score"], reverse=True)
    return items[:limit]


def store_rag_example(
    db: Session,
    plugin_id: str,
    dataset_id: Optional[str],
    question: str,
    sql: str,
    answer_summary: Optional[str],
    quality_score: float = 0.8,
    source: str = "auto_success",
    rewritten_question: Optional[str] = None,
) -> Optional[RAGExample]:
    if not (question or "").strip() or not (sql or "").strip():
        return None
    existing = db.query(RAGExample).filter(
        RAGExample.plugin_id == plugin_id,
        RAGExample.dataset_id == dataset_id,
        RAGExample.question == question.strip(),
        RAGExample.sql == sql.strip(),
    ).first()
    if existing:
        existing.quality_score = max(float(existing.quality_score or 0), float(quality_score))
        existing.answer_summary = answer_summary or existing.answer_summary
        existing.updated_at = datetime.utcnow()
        db.commit()
        return existing
    row = RAGExample(
        plugin_id=plugin_id,
        dataset_id=dataset_id,
        question=question.strip(),
        rewritten_question=(rewritten_question or "").strip() or None,
        sql=sql.strip(),
        answer_summary=(answer_summary or "").strip() or None,
        quality_score=quality_score,
        source=source,
        updated_at=datetime.utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def retrieve_rag_examples(
    db: Session,
    plugin_id: str,
    question: str,
    dataset_id: Optional[str] = None,
    limit: int = 6,
) -> List[Dict[str, Any]]:
    q = db.query(RAGExample).filter(RAGExample.plugin_id == plugin_id, RAGExample.is_active == True)  # noqa: E712
    if dataset_id:
        q = q.filter((RAGExample.dataset_id == dataset_id) | (RAGExample.dataset_id.is_(None)))
    rows = q.order_by(RAGExample.updated_at.desc()).limit(300).all()
    q_tokens = tokenize_text(question)
    scored: List[Tuple[float, RAGExample]] = []
    for row in rows:
        text_blob = f"{row.question} {row.rewritten_question or ''} {row.answer_summary or ''}"
        score = _sim_score(q_tokens, tokenize_text(text_blob), text_blob)
        score += float(row.quality_score or 0) * 0.2
        if score <= 0:
            continue
        scored.append((score, row))
    # also use corrected feedback SQL as examples when no explicit examples found
    if len(scored) < limit:
        fb_rows = db.query(QueryFeedback).filter(
            QueryFeedback.plugin_id == plugin_id,
            QueryFeedback.corrected_sql.isnot(None),
        ).order_by(QueryFeedback.created_at.desc()).limit(100).all()
        for fb in fb_rows:
            text_blob = f"{fb.question} {fb.comment or ''}"
            score = _sim_score(q_tokens, tokenize_text(text_blob), text_blob)
            if score <= 0:
                continue
            dummy = RAGExample(
                plugin_id=plugin_id,
                dataset_id=dataset_id,
                question=fb.question or "",
                rewritten_question=None,
                sql=fb.corrected_sql or "",
                answer_summary=fb.comment or "",
                quality_score=0.75,
                source="feedback",
            )
            scored.append((score + 0.05, dummy))

    scored.sort(key=lambda x: x[0], reverse=True)
    out: List[Dict[str, Any]] = []
    for score, row in scored[:limit]:
        out.append({
            "source_type": "example",
            "id": str(getattr(row, "example_id", "")) or f"example:{hash(row.question + row.sql)}",
            "score": round(score, 4),
            "title": (row.question or "")[:120],
            "snippet": f"Q: {row.question}\nSQL: {row.sql}\nA: {row.answer_summary or ''}"[:900],
            "metadata": {
                "sql": row.sql,
                "source": row.source,
                "quality_score": float(row.quality_score or 0),
            },
        })
    return out


def rewrite_user_query(
    question: str,
    conversation_history: Optional[List[dict]] = None,
) -> str:
    question = (question or "").strip()
    if not question:
        return question

    # Heuristic quick path.
    if len(question.split()) >= 4 and not re.search(r"\b(it|that|those|them|this|same)\b", question.lower()):
        return question

    # Optional LLM rewrite.
    if os.getenv("RAG_QUERY_REWRITE_ENABLED", "true").lower() not in {"1", "true", "yes"}:
        return question
    cfg = LLMConfig()
    if not cfg.available:
        return question

    history_text = ""
    if conversation_history:
        lines = []
        for turn in conversation_history[-6:]:
            role = (turn.get("role") or "user").lower()
            content = (turn.get("content") or "")[:300]
            lines.append(f"{role}: {content}")
        history_text = "\n".join(lines)

    prompt = (
        "Rewrite the final user question into a standalone analytics question.\n"
        "Keep intent unchanged. Do not invent new metrics.\n"
        "Return only the rewritten question.\n\n"
        f"Conversation:\n{history_text}\n\n"
        f"Final question: {question}"
    )
    try:
        rewritten = generate_text_response(
            system_prompt="You rewrite follow-up questions into standalone data analysis questions.",
            user_prompt=prompt,
            config=cfg,
            temperature=0,
            max_tokens=180,
        ).strip()
        if rewritten:
            return rewritten[:500]
    except Exception as e:
        logger.debug(f"Query rewrite failed, using original question: {e}")
    return question


def rerank_contexts(question: str, contexts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not contexts:
        return []
    q_tokens = tokenize_text(question)
    for item in contexts:
        base = float(item.get("score", 0))
        snippet = (item.get("snippet") or "")[:1000]
        rerank = _sim_score(q_tokens, tokenize_text(snippet), snippet)
        # Source-type priors
        stype = item.get("source_type")
        if stype == "schema":
            rerank += 0.05
        if stype == "example":
            rerank += 0.03
        item["rerank_score"] = round(base * 0.7 + rerank * 0.3, 4)
    return sorted(contexts, key=lambda x: x.get("rerank_score", 0), reverse=True)


def pack_context_for_prompt(contexts: List[Dict[str, Any]], max_chars: int = 4500) -> Tuple[str, List[Dict[str, Any]]]:
    packed_lines: List[str] = []
    citations: List[Dict[str, Any]] = []
    used = 0
    for item in contexts:
        title = item.get("title") or item.get("id") or "context"
        stype = item.get("source_type", "context")
        snippet = (item.get("snippet") or "").strip()
        if not snippet:
            continue
        block = f"[{stype}] {title}\n{snippet}\n"
        if used + len(block) > max_chars:
            break
        packed_lines.append(block)
        used += len(block)
        citations.append({
            "source_type": stype,
            "id": item.get("id"),
            "title": title,
            "score": item.get("rerank_score", item.get("score", 0)),
        })
    return "\n".join(packed_lines), citations


def enqueue_review_item(
    db: Session,
    plugin_id: str,
    dataset_id: Optional[str],
    question: str,
    rewritten_question: Optional[str],
    proposed_sql: Optional[str],
    reason: str,
    confidence: Optional[str],
    context_payload: Optional[dict] = None,
) -> HumanReviewQueue:
    row = HumanReviewQueue(
        plugin_id=plugin_id,
        dataset_id=dataset_id,
        question=question,
        rewritten_question=rewritten_question,
        proposed_sql=proposed_sql,
        reason=reason,
        confidence=confidence,
        context_payload=context_payload or {},
        updated_at=datetime.utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_review_queue(
    db: Session,
    plugin_id: Optional[str] = None,
    status: str = "open",
    limit: int = 100,
) -> List[HumanReviewQueue]:
    q = db.query(HumanReviewQueue)
    if plugin_id:
        q = q.filter(HumanReviewQueue.plugin_id == plugin_id)
    if status:
        q = q.filter(HumanReviewQueue.status == status)
    return q.order_by(HumanReviewQueue.created_at.desc()).limit(limit).all()


def resolve_review_item(
    db: Session,
    review_id: UUID,
    status: str,
    resolution_notes: Optional[str] = None,
    resolved_sql: Optional[str] = None,
    resolved_by: Optional[str] = None,
) -> Optional[HumanReviewQueue]:
    row = db.query(HumanReviewQueue).filter(HumanReviewQueue.review_id == review_id).first()
    if not row:
        return None
    row.status = status
    row.resolution_notes = resolution_notes
    row.resolved_sql = resolved_sql
    row.resolved_by = resolved_by
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    # If approved with SQL, promote as high-quality example.
    if status == "approved" and resolved_sql:
        store_rag_example(
            db,
            plugin_id=row.plugin_id,
            dataset_id=row.dataset_id,
            question=row.question,
            sql=resolved_sql,
            answer_summary=resolution_notes or "Human approved SQL",
            quality_score=0.95,
            source="human_approved",
            rewritten_question=row.rewritten_question,
        )
    return row


def run_golden_eval(
    db: Session,
    plugin_id: str,
    dataset_id: Optional[str] = None,
    cases_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Lightweight evaluation framework:
    - Intent classification accuracy on golden questions
    - Retrieval hit-rate for KB/examples
    """
    _ = db  # reserved for future richer checks
    path = cases_path or str(Path(__file__).resolve().parent / "tests" / "golden_questions.json")
    p = Path(path)
    if not p.exists():
        return {"status": "error", "message": f"golden file not found: {path}"}
    cases = json.loads(p.read_text(encoding="utf-8"))
    total = len(cases)
    if total == 0:
        return {"status": "error", "message": "golden cases empty"}

    intent_ok = 0
    retrieval_hits = 0
    per_case = []
    for case in cases:
        question = case.get("question", "")
        expected_intent = case.get("expected_intent")
        actual_intent = nl_to_sql.classify_intent(question)
        if expected_intent and actual_intent == expected_intent:
            intent_ok += 1
        kb = retrieve_kb_chunks(db, plugin_id=plugin_id, dataset_id=dataset_id, question=question, limit=3)
        ex = retrieve_rag_examples(db, plugin_id=plugin_id, dataset_id=dataset_id, question=question, limit=2)
        hit = 1 if (kb or ex) else 0
        retrieval_hits += hit
        per_case.append({
            "question": question,
            "expected_intent": expected_intent,
            "actual_intent": actual_intent,
            "kb_hits": len(kb),
            "example_hits": len(ex),
        })

    return {
        "status": "ok",
        "total_cases": total,
        "intent_accuracy": round(intent_ok / total, 4),
        "retrieval_hit_rate": round(retrieval_hits / total, 4),
        "cases": per_case,
    }
