"""
RAG routes:
- Knowledge base ingestion/search
- RAG examples
- Human review queue
- Evaluation
"""

from __future__ import annotations

from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.helpers import parse_uuid
from app.models import KnowledgeDocument, RAGExample
from app.rag_service import (
    ingest_knowledge_document,
    retrieve_kb_chunks,
    retrieve_rag_examples,
    list_review_queue,
    resolve_review_item,
    run_golden_eval,
)

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class KnowledgeIngestRequest(BaseModel):
    plugin_id: str
    dataset_id: Optional[str] = None
    title: str
    content: Optional[str] = None
    source_type: Optional[str] = "manual"
    source_uri: Optional[str] = None
    metadata_json: Optional[dict] = None


class ReviewResolveRequest(BaseModel):
    status: str  # approved|rejected|resolved
    resolution_notes: Optional[str] = None
    resolved_sql: Optional[str] = None
    resolved_by: Optional[str] = None


def _doc_dict(d: KnowledgeDocument) -> dict:
    return {
        "doc_id": str(d.doc_id),
        "plugin_id": d.plugin_id,
        "dataset_id": d.dataset_id,
        "title": d.title,
        "source_type": d.source_type,
        "source_uri": d.source_uri,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
        "is_active": bool(d.is_active),
    }


@router.post("/rag/kb")
def ingest_kb(req: KnowledgeIngestRequest, db: Session = Depends(get_db)):
    try:
        doc = ingest_knowledge_document(
            db=db,
            plugin_id=req.plugin_id,
            dataset_id=req.dataset_id,
            title=req.title,
            content=req.content,
            source_type=req.source_type or "manual",
            source_uri=req.source_uri,
            metadata_json=req.metadata_json,
        )
        return _doc_dict(doc)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"KB ingest failed: {e}")


@router.get("/rag/kb")
def list_kb_docs(
    plugin_id: Optional[str] = Query(None),
    dataset_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    q = db.query(KnowledgeDocument).filter(KnowledgeDocument.is_active == True)  # noqa: E712
    if plugin_id:
        q = q.filter(KnowledgeDocument.plugin_id == plugin_id)
    if dataset_id:
        q = q.filter(KnowledgeDocument.dataset_id == dataset_id)
    rows = q.order_by(KnowledgeDocument.updated_at.desc()).limit(limit).all()
    return [_doc_dict(r) for r in rows]


@router.get("/rag/kb/search")
def search_kb(
    plugin_id: str = Query(...),
    question: str = Query(...),
    dataset_id: Optional[str] = Query(None),
    limit: int = Query(8, ge=1, le=30),
    db: Session = Depends(get_db),
):
    return retrieve_kb_chunks(db, plugin_id=plugin_id, dataset_id=dataset_id, question=question, limit=limit)


@router.get("/rag/examples")
def list_examples(
    plugin_id: str = Query(...),
    question: Optional[str] = Query(None),
    dataset_id: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    if question:
        return retrieve_rag_examples(db, plugin_id=plugin_id, dataset_id=dataset_id, question=question, limit=limit)
    q = db.query(RAGExample).filter(RAGExample.plugin_id == plugin_id, RAGExample.is_active == True)  # noqa: E712
    if dataset_id:
        q = q.filter((RAGExample.dataset_id == dataset_id) | (RAGExample.dataset_id.is_(None)))
    rows = q.order_by(RAGExample.updated_at.desc()).limit(limit).all()
    return [
        {
            "example_id": str(r.example_id),
            "plugin_id": r.plugin_id,
            "dataset_id": r.dataset_id,
            "question": r.question,
            "rewritten_question": r.rewritten_question,
            "sql": r.sql,
            "answer_summary": r.answer_summary,
            "quality_score": float(r.quality_score or 0),
            "source": r.source,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in rows
    ]


@router.get("/rag/review")
def get_review_queue(
    plugin_id: Optional[str] = Query(None),
    status: str = Query("open"),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    rows = list_review_queue(db, plugin_id=plugin_id, status=status, limit=limit)
    return [
        {
            "review_id": str(r.review_id),
            "plugin_id": r.plugin_id,
            "dataset_id": r.dataset_id,
            "question": r.question,
            "rewritten_question": r.rewritten_question,
            "proposed_sql": r.proposed_sql,
            "reason": r.reason,
            "confidence": r.confidence,
            "status": r.status,
            "resolution_notes": r.resolution_notes,
            "resolved_sql": r.resolved_sql,
            "resolved_by": r.resolved_by,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in rows
    ]


@router.post("/rag/review/{review_id}/resolve")
def resolve_review(review_id: str, req: ReviewResolveRequest, db: Session = Depends(get_db)):
    rid = parse_uuid(review_id, "review_id")
    if req.status not in {"approved", "rejected", "resolved"}:
        raise HTTPException(status_code=400, detail="status must be approved|rejected|resolved")
    row = resolve_review_item(
        db=db,
        review_id=rid,
        status=req.status,
        resolution_notes=req.resolution_notes,
        resolved_sql=req.resolved_sql,
        resolved_by=req.resolved_by,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Review item not found")
    return {"status": "ok", "review_id": review_id, "new_status": row.status}


@router.get("/rag/eval")
def run_eval(
    plugin_id: str = Query(...),
    dataset_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    return run_golden_eval(db, plugin_id=plugin_id, dataset_id=dataset_id)
