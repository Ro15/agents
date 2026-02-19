"""
Agent routes:
- User profile/persona memory
- Goal planning & execution loop
- Approval checkpoints
- Automation tasks
- Agent metrics
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.helpers import parse_uuid
from app.models import AgentUserProfile, AgentGoal, AgentPlanStep, AgentAutomation
from app.agent_service import (
    get_or_create_profile,
    update_profile_from_text,
    create_goal_with_plan,
    execute_goal,
    compute_agent_metrics,
    create_automation,
)

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class AgentProfileUpdateRequest(BaseModel):
    user_id: str
    plugin_id: str
    response_style: Optional[str] = None
    preferred_chart_types: Optional[list[str]] = None
    preferred_kpis: Optional[list[str]] = None
    timezone: Optional[str] = None
    notes: Optional[str] = None


class AgentGoalCreateRequest(BaseModel):
    plugin_id: str
    dataset_id: Optional[str] = None
    user_id: Optional[str] = None
    thread_id: Optional[str] = None
    goal_text: str
    priority: Optional[str] = "normal"


class AgentGoalRunRequest(BaseModel):
    auto_approve: Optional[bool] = False
    max_steps: Optional[int] = 20
    approval_token: Optional[str] = None


class AgentGoalApproveRequest(BaseModel):
    approval_token: str


class AgentAutomationCreateRequest(BaseModel):
    plugin_id: str
    dataset_id: Optional[str] = None
    user_id: Optional[str] = None
    title: str
    goal_text: str
    task_type: Optional[str] = "monitor"
    schedule_cron: Optional[str] = "0 8 * * *"
    config: Optional[dict] = None


class AgentAutomationUpdateRequest(BaseModel):
    title: Optional[str] = None
    goal_text: Optional[str] = None
    task_type: Optional[str] = None
    schedule_cron: Optional[str] = None
    enabled: Optional[bool] = None
    config: Optional[dict] = None


def _profile_dict(p: AgentUserProfile) -> dict:
    return {
        "profile_id": str(p.profile_id),
        "user_id": p.user_id,
        "plugin_id": p.plugin_id,
        "response_style": p.response_style,
        "preferred_chart_types": p.preferred_chart_types or [],
        "preferred_kpis": p.preferred_kpis or [],
        "timezone": p.timezone,
        "notes": p.notes,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


def _goal_dict(g: AgentGoal) -> dict:
    return {
        "goal_id": str(g.goal_id),
        "plugin_id": g.plugin_id,
        "dataset_id": g.dataset_id,
        "user_id": g.user_id,
        "thread_id": g.thread_id,
        "title": g.title,
        "goal_text": g.goal_text,
        "status": g.status,
        "priority": g.priority,
        "requires_human_approval": bool(g.requires_human_approval),
        "approval_token": g.approval_token,
        "working_memory": g.working_memory,
        "result_summary": g.result_summary,
        "created_at": g.created_at.isoformat() if g.created_at else None,
        "updated_at": g.updated_at.isoformat() if g.updated_at else None,
        "completed_at": g.completed_at.isoformat() if g.completed_at else None,
    }


def _step_dict(s: AgentPlanStep) -> dict:
    return {
        "step_id": str(s.step_id),
        "goal_id": str(s.goal_id),
        "step_order": s.step_order,
        "title": s.title,
        "description": s.description,
        "tool_name": s.tool_name,
        "status": s.status,
        "requires_approval": bool(s.requires_approval),
        "input_payload": s.input_payload,
        "output_payload": s.output_payload,
        "error": s.error,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


def _automation_dict(a: AgentAutomation) -> dict:
    return {
        "automation_id": str(a.automation_id),
        "plugin_id": a.plugin_id,
        "dataset_id": a.dataset_id,
        "user_id": a.user_id,
        "title": a.title,
        "goal_text": a.goal_text,
        "task_type": a.task_type,
        "schedule_cron": a.schedule_cron,
        "enabled": bool(a.enabled),
        "config": a.config or {},
        "last_run_at": a.last_run_at.isoformat() if a.last_run_at else None,
        "next_run_at": a.next_run_at.isoformat() if a.next_run_at else None,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "updated_at": a.updated_at.isoformat() if a.updated_at else None,
    }


@router.get("/agent/profile")
def get_agent_profile(user_id: str = Query(...), plugin_id: str = Query(...), db: Session = Depends(get_db)):
    row = get_or_create_profile(db, user_id=user_id, plugin_id=plugin_id)
    return _profile_dict(row)


@router.put("/agent/profile")
def update_agent_profile(req: AgentProfileUpdateRequest, db: Session = Depends(get_db)):
    row = get_or_create_profile(db, user_id=req.user_id, plugin_id=req.plugin_id)
    if req.response_style is not None:
        row.response_style = req.response_style
    if req.preferred_chart_types is not None:
        row.preferred_chart_types = req.preferred_chart_types
    if req.preferred_kpis is not None:
        row.preferred_kpis = req.preferred_kpis
    if req.timezone is not None:
        row.timezone = req.timezone
    if req.notes is not None:
        row.notes = req.notes
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return _profile_dict(row)


@router.post("/agent/profile/infer")
def infer_agent_profile(user_id: str = Query(...), plugin_id: str = Query(...), text_value: str = Query(...), db: Session = Depends(get_db)):
    row = update_profile_from_text(db, user_id=user_id, plugin_id=plugin_id, text_value=text_value)
    return _profile_dict(row)


@router.post("/agent/goals")
def create_agent_goal(req: AgentGoalCreateRequest, db: Session = Depends(get_db)):
    if not (req.goal_text or "").strip():
        raise HTTPException(status_code=400, detail="goal_text is required")
    goal = create_goal_with_plan(
        db,
        plugin_id=req.plugin_id,
        dataset_id=req.dataset_id,
        goal_text=req.goal_text,
        user_id=req.user_id,
        thread_id=req.thread_id,
        priority=req.priority or "normal",
    )
    steps = db.query(AgentPlanStep).filter(AgentPlanStep.goal_id == goal.goal_id).order_by(AgentPlanStep.step_order.asc()).all()
    return {"goal": _goal_dict(goal), "steps": [_step_dict(s) for s in steps]}


@router.get("/agent/goals")
def list_agent_goals(
    plugin_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    q = db.query(AgentGoal)
    if plugin_id:
        q = q.filter(AgentGoal.plugin_id == plugin_id)
    if user_id:
        q = q.filter(AgentGoal.user_id == user_id)
    if status:
        q = q.filter(AgentGoal.status == status)
    rows = q.order_by(AgentGoal.created_at.desc()).limit(limit).all()
    return [_goal_dict(r) for r in rows]


@router.get("/agent/goals/{goal_id}")
def get_agent_goal(goal_id: str, db: Session = Depends(get_db)):
    gid = parse_uuid(goal_id, "goal_id")
    g = db.query(AgentGoal).filter(AgentGoal.goal_id == gid).first()
    if not g:
        raise HTTPException(status_code=404, detail="Goal not found")
    steps = db.query(AgentPlanStep).filter(AgentPlanStep.goal_id == gid).order_by(AgentPlanStep.step_order.asc()).all()
    return {"goal": _goal_dict(g), "steps": [_step_dict(s) for s in steps]}


@router.post("/agent/goals/{goal_id}/run")
def run_agent_goal(goal_id: str, req: AgentGoalRunRequest, db: Session = Depends(get_db)):
    gid = parse_uuid(goal_id, "goal_id")
    try:
        out = execute_goal(
            db,
            goal_id=gid,
            auto_approve=bool(req.auto_approve),
            max_steps=int(req.max_steps or 20),
            approval_token=req.approval_token,
        )
        g = db.query(AgentGoal).filter(AgentGoal.goal_id == gid).first()
        steps = db.query(AgentPlanStep).filter(AgentPlanStep.goal_id == gid).order_by(AgentPlanStep.step_order.asc()).all()
        return {"run": out, "goal": _goal_dict(g), "steps": [_step_dict(s) for s in steps]}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/agent/goals/{goal_id}/approve")
def approve_agent_goal(goal_id: str, req: AgentGoalApproveRequest, db: Session = Depends(get_db)):
    gid = parse_uuid(goal_id, "goal_id")
    g = db.query(AgentGoal).filter(AgentGoal.goal_id == gid).first()
    if not g:
        raise HTTPException(status_code=404, detail="Goal not found")
    if not g.approval_token or g.approval_token != req.approval_token:
        raise HTTPException(status_code=400, detail="Invalid approval token")
    out = execute_goal(db, goal_id=gid, auto_approve=True, max_steps=20, approval_token=req.approval_token)
    return {"status": "approved_and_resumed", "run": out}


@router.post("/agent/automations")
def create_agent_automation(req: AgentAutomationCreateRequest, db: Session = Depends(get_db)):
    row = create_automation(
        db,
        plugin_id=req.plugin_id,
        dataset_id=req.dataset_id,
        user_id=req.user_id,
        title=req.title,
        goal_text=req.goal_text,
        task_type=req.task_type or "monitor",
        schedule_cron=req.schedule_cron or "0 8 * * *",
        config=req.config,
    )
    return _automation_dict(row)


@router.get("/agent/automations")
def list_agent_automations(
    plugin_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    enabled: Optional[bool] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    q = db.query(AgentAutomation)
    if plugin_id:
        q = q.filter(AgentAutomation.plugin_id == plugin_id)
    if user_id:
        q = q.filter(AgentAutomation.user_id == user_id)
    if enabled is not None:
        q = q.filter(AgentAutomation.enabled == enabled)
    rows = q.order_by(AgentAutomation.created_at.desc()).limit(limit).all()
    return [_automation_dict(r) for r in rows]


@router.put("/agent/automations/{automation_id}")
def update_agent_automation(automation_id: str, req: AgentAutomationUpdateRequest, db: Session = Depends(get_db)):
    aid = parse_uuid(automation_id, "automation_id")
    row = db.query(AgentAutomation).filter(AgentAutomation.automation_id == aid).first()
    if not row:
        raise HTTPException(status_code=404, detail="Automation not found")
    if req.title is not None:
        row.title = req.title
    if req.goal_text is not None:
        row.goal_text = req.goal_text
    if req.task_type is not None:
        row.task_type = req.task_type
    if req.schedule_cron is not None:
        row.schedule_cron = req.schedule_cron
    if req.enabled is not None:
        row.enabled = req.enabled
    if req.config is not None:
        row.config = req.config
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return _automation_dict(row)


@router.delete("/agent/automations/{automation_id}")
def delete_agent_automation(automation_id: str, db: Session = Depends(get_db)):
    aid = parse_uuid(automation_id, "automation_id")
    row = db.query(AgentAutomation).filter(AgentAutomation.automation_id == aid).first()
    if not row:
        raise HTTPException(status_code=404, detail="Automation not found")
    db.delete(row)
    db.commit()
    return {"status": "deleted", "automation_id": automation_id}


@router.post("/agent/automations/{automation_id}/run-now")
def run_automation_now(automation_id: str, db: Session = Depends(get_db)):
    aid = parse_uuid(automation_id, "automation_id")
    row = db.query(AgentAutomation).filter(AgentAutomation.automation_id == aid).first()
    if not row:
        raise HTTPException(status_code=404, detail="Automation not found")
    goal = create_goal_with_plan(
        db,
        plugin_id=row.plugin_id,
        dataset_id=row.dataset_id,
        goal_text=row.goal_text,
        user_id=row.user_id,
        priority="normal",
    )
    result = execute_goal(db, goal.goal_id, auto_approve=False, max_steps=20)
    row.last_run_at = datetime.utcnow()
    row.updated_at = datetime.utcnow()
    db.commit()
    return {"automation": _automation_dict(row), "goal_id": str(goal.goal_id), "run": result}


@router.post("/agent/automations/run-due")
def run_due_automations(
    plugin_id: Optional[str] = Query(None),
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    now = datetime.utcnow()
    q = db.query(AgentAutomation).filter(AgentAutomation.enabled == True)  # noqa: E712
    if plugin_id:
        q = q.filter(AgentAutomation.plugin_id == plugin_id)
    rows = q.order_by(AgentAutomation.last_run_at.asc()).limit(limit).all()
    runs = []
    for row in rows:
        if row.next_run_at and row.next_run_at > now:
            continue
        goal = create_goal_with_plan(
            db,
            plugin_id=row.plugin_id,
            dataset_id=row.dataset_id,
            goal_text=row.goal_text,
            user_id=row.user_id,
            priority="normal",
        )
        result = execute_goal(db, goal.goal_id, auto_approve=False, max_steps=20)
        row.last_run_at = now
        # lightweight scheduler fallback: run again in 24h unless custom cadence is supplied later.
        row.next_run_at = now + timedelta(days=1)
        row.updated_at = now
        db.commit()
        runs.append({
            "automation_id": str(row.automation_id),
            "goal_id": str(goal.goal_id),
            "status": result.get("status"),
            "requires_human_approval": result.get("requires_human_approval"),
        })
    return {"triggered": len(runs), "runs": runs, "run_at": now.isoformat()}


@router.get("/agent/metrics")
def get_agent_metrics(
    plugin_id: Optional[str] = Query(None),
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    return compute_agent_metrics(db, plugin_id=plugin_id, days=days)
