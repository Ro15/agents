"""
Agent orchestration service:
- Goal planning (tool selection + steps)
- Step-by-step execution loop
- Approval guardrails
- Persona/profile memory
- Automation run helpers
- Agent quality metrics
"""

from __future__ import annotations

import logging
import os
import re
import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app import nl_to_sql
from app.helpers import ensure_active_plugin
from app.llm_service import LLMConfig, generate_text_response, verify_sql_with_llm, SchemaContext
from app.models import (
    AgentGoal,
    AgentPlanStep,
    AgentUserProfile,
    AgentAutomation,
    Dataset,
    QueryHistoryEntry,
    QueryFeedback,
)
from app.rag_service import (
    retrieve_kb_chunks,
    retrieve_rag_examples,
    retrieve_schema_snippets,
    rerank_contexts,
    pack_context_for_prompt,
    store_rag_example,
)

logger = logging.getLogger(__name__)


TOOL_CATALOG = {
    "schema_retrieval": "Retrieve relevant tables/columns/joins for the goal.",
    "kb_retrieval": "Retrieve business docs and KPI definitions.",
    "example_retrieval": "Retrieve similar successful Q->SQL examples.",
    "sql_generation": "Generate SQL candidate for the target question.",
    "sql_verifier": "Verify SQL-question alignment and safe constraints.",
    "sql_execution": "Execute SQL and collect structured results.",
    "anomaly_scan": "Check for outliers/sharp changes in the result.",
    "summary_writer": "Write concise analyst-style summary.",
}


def _normalize_goal_title(goal_text: str) -> str:
    txt = (goal_text or "").strip()
    if not txt:
        return "Data analysis goal"
    return txt[:80]


def _extract_focus_question(goal_text: str) -> str:
    text_value = (goal_text or "").strip()
    if not text_value:
        return "Summarize key metrics for the selected data."
    return text_value


def _detect_response_style(text_value: str) -> Optional[str]:
    q = (text_value or "").lower()
    if any(k in q for k in ("short answer", "brief", "concise")):
        return "concise"
    if any(k in q for k in ("detailed", "deep dive", "explain fully", "full details")):
        return "detailed"
    return None


def _is_risky_sql(sql: str) -> bool:
    if not sql:
        return True
    low = sql.lower()
    # guardrail patterns for large-cost operations
    if " limit " not in f" {low} ":
        return True
    if " where " not in f" {low} " and " group by " not in f" {low} ":
        return True
    if re.search(r"\bselect\s+\*\s+from\b", low):
        return True
    return False


def _build_schema_context(active_plugin) -> SchemaContext:
    return SchemaContext(
        active_plugin.schema,
        active_plugin.get_allowed_tables(),
        active_plugin.get_allowed_columns(),
        plugin_name=active_plugin.plugin_name,
        metrics_description=active_plugin.get_metrics_description(),
        views=getattr(active_plugin, "compiled_views", []),
        business_glossary=active_plugin.get_business_glossary() if hasattr(active_plugin, "get_business_glossary") else [],
        relationships_description=active_plugin.get_relationships_description(),
        schema_description=active_plugin.get_schema_description(),
    )


def get_or_create_profile(
    db: Session,
    user_id: str,
    plugin_id: str,
) -> AgentUserProfile:
    row = db.query(AgentUserProfile).filter(
        AgentUserProfile.user_id == user_id,
        AgentUserProfile.plugin_id == plugin_id,
    ).first()
    if row:
        return row
    row = AgentUserProfile(
        user_id=user_id,
        plugin_id=plugin_id,
        response_style="concise",
        preferred_chart_types=[],
        preferred_kpis=[],
        updated_at=datetime.utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_profile_from_text(
    db: Session,
    user_id: Optional[str],
    plugin_id: str,
    text_value: str,
) -> Optional[AgentUserProfile]:
    if not user_id:
        return None
    row = get_or_create_profile(db, user_id=user_id, plugin_id=plugin_id)
    style = _detect_response_style(text_value)
    if style and row.response_style != style:
        row.response_style = style
    # light KPI preference extraction
    kpis = set(row.preferred_kpis or [])
    for token in ("revenue", "sales", "margin", "profit", "aov", "conversion", "returns"):
        if re.search(rf"\b{token}\b", (text_value or "").lower()):
            kpis.add(token)
    row.preferred_kpis = sorted(kpis)[:25]
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return row


def _heuristic_plan(goal_text: str) -> List[Dict[str, Any]]:
    q = (goal_text or "").lower()
    steps = [
        {"title": "Collect schema context", "tool_name": "schema_retrieval"},
        {"title": "Collect business context", "tool_name": "kb_retrieval"},
        {"title": "Collect similar examples", "tool_name": "example_retrieval"},
        {"title": "Generate SQL", "tool_name": "sql_generation"},
        {"title": "Verify SQL", "tool_name": "sql_verifier"},
        {"title": "Execute SQL", "tool_name": "sql_execution"},
        {"title": "Write analyst summary", "tool_name": "summary_writer"},
    ]
    if any(k in q for k in ("anomaly", "drop", "spike", "sudden", "outlier")):
        steps.insert(6, {"title": "Scan anomalies", "tool_name": "anomaly_scan"})
    return steps


def plan_goal(
    goal_text: str,
    active_plugin,
    profile: Optional[AgentUserProfile] = None,
) -> Dict[str, Any]:
    """
    Generate an executable plan. Uses LLM planner if available, else heuristic plan.
    """
    base_steps = _heuristic_plan(goal_text)
    cfg = LLMConfig()
    if cfg.available and os.getenv("AGENT_LLM_PLANNER_ENABLED", "true").lower() in {"1", "true", "yes"}:
        try:
            tool_names = ", ".join(sorted(TOOL_CATALOG.keys()))
            profile_block = ""
            if profile:
                profile_block = (
                    f"User style: {profile.response_style}\n"
                    f"Preferred KPIs: {', '.join(profile.preferred_kpis or [])}\n"
                )
            prompt = (
                "Plan a data analyst workflow using only these tools:\n"
                f"{tool_names}\n\n"
                "Return one step per line in format: tool_name | title\n\n"
                f"Goal: {goal_text}\n"
                f"{profile_block}"
            )
            txt = generate_text_response(
                system_prompt="You are an analytics agent planner. Keep plans short and executable.",
                user_prompt=prompt,
                config=cfg,
                temperature=0,
                max_tokens=300,
            )
            parsed = []
            for line in (txt or "").splitlines():
                line = line.strip()
                if "|" not in line:
                    continue
                tool, title = [x.strip() for x in line.split("|", 1)]
                if tool in TOOL_CATALOG:
                    parsed.append({"tool_name": tool, "title": title or TOOL_CATALOG[tool]})
            if parsed:
                base_steps = parsed[:10]
        except Exception as e:
            logger.debug(f"LLM planner failed; using heuristic plan: {e}")

    plan = []
    for idx, s in enumerate(base_steps, start=1):
        plan.append({
            "step_order": idx,
            "title": s["title"],
            "description": TOOL_CATALOG.get(s["tool_name"], ""),
            "tool_name": s["tool_name"],
        })
    return {"title": _normalize_goal_title(goal_text), "steps": plan}


def create_goal_with_plan(
    db: Session,
    plugin_id: str,
    dataset_id: Optional[str],
    goal_text: str,
    user_id: Optional[str] = None,
    thread_id: Optional[str] = None,
    priority: str = "normal",
) -> AgentGoal:
    active_plugin = ensure_active_plugin(plugin_id)
    profile = update_profile_from_text(db, user_id=user_id, plugin_id=plugin_id, text_value=goal_text) if user_id else None
    plan = plan_goal(goal_text, active_plugin=active_plugin, profile=profile)
    goal = AgentGoal(
        plugin_id=plugin_id,
        dataset_id=dataset_id,
        user_id=user_id,
        thread_id=thread_id,
        title=plan["title"],
        goal_text=goal_text,
        priority=priority if priority in {"low", "normal", "high"} else "normal",
        status="open",
        working_memory={"focus_question": _extract_focus_question(goal_text), "plan_notes": []},
        updated_at=datetime.utcnow(),
    )
    db.add(goal)
    db.flush()
    for s in plan["steps"]:
        db.add(AgentPlanStep(
            goal_id=goal.goal_id,
            step_order=s["step_order"],
            title=s["title"],
            description=s["description"],
            tool_name=s["tool_name"],
            status="pending",
            input_payload={},
        ))
    db.commit()
    db.refresh(goal)
    return goal


def _run_step_schema_retrieval(active_plugin, question: str, dataset_id: Optional[str], db: Session):
    snippets = retrieve_schema_snippets(active_plugin, question=question, dynamic_columns=None, dynamic_table=None, limit=8)
    return {"items": snippets, "count": len(snippets)}


def _run_step_kb_retrieval(active_plugin, question: str, dataset_id: Optional[str], db: Session):
    rows = retrieve_kb_chunks(db, plugin_id=active_plugin.plugin_name, question=question, dataset_id=dataset_id, limit=8)
    return {"items": rows, "count": len(rows)}


def _run_step_example_retrieval(active_plugin, question: str, dataset_id: Optional[str], db: Session):
    rows = retrieve_rag_examples(db, plugin_id=active_plugin.plugin_name, question=question, dataset_id=dataset_id, limit=6)
    return {"items": rows, "count": len(rows)}


def _build_learning_context_from_steps(step_outputs: Dict[str, Any]) -> str:
    parts = []
    for key in ("schema_retrieval", "kb_retrieval", "example_retrieval"):
        val = step_outputs.get(key)
        if not val:
            continue
        items = val.get("items", [])
        if not items:
            continue
        packed, _ = pack_context_for_prompt(items, max_chars=2500)
        if packed:
            parts.append(f"{key}:\n{packed}")
    return "\n\n".join(parts)


def _run_step_sql_generation(active_plugin, question: str, dataset_id: Optional[str], db: Session, step_outputs: Dict[str, Any]):
    ds_version = 0
    if dataset_id:
        try:
            ds_uuid = UUID(str(dataset_id))
            ds = db.query(Dataset).filter(Dataset.dataset_id == ds_uuid).first()
            ds_version = int(ds.version or 0) if ds else 0
        except Exception:
            ds_version = 0
    learning_context = _build_learning_context_from_steps(step_outputs)
    res = nl_to_sql.generate_sql(
        question,
        dataset_id=str(dataset_id or ""),
        dataset_version=ds_version,
        learning_context=learning_context,
        use_cache=True,
    )
    return {
        "sql": res.sql,
        "answer_type": res.answer_type,
        "confidence": res.confidence,
        "assumptions": res.assumptions,
        "failure_reason": res.failure_reason,
    }


def _run_step_sql_verifier(active_plugin, question: str, sql: str):
    ctx = _build_schema_context(active_plugin)
    verify = verify_sql_with_llm(question=question, sql=sql, schema_context=ctx, config=LLMConfig())
    return verify


def _run_step_sql_execution(active_plugin, sql: str, dataset_id: Optional[str], db: Session, auto_approve: bool):
    if _is_risky_sql(sql) and not auto_approve:
        token = secrets.token_urlsafe(16)
        return {"requires_approval": True, "approval_token": token, "reason": "risky_sql_detected"}
    scoped = sql
    params = {}
    if dataset_id:
        scoped = nl_to_sql.SQL_GUARD.enforce_dataset_filter(sql, "dataset_id")
        try:
            params["dataset_id"] = UUID(str(dataset_id))
        except Exception:
            params["dataset_id"] = dataset_id
    rows = db.execute(text(scoped), params).fetchall()
    if len(rows) == 1 and len(rows[0]) == 1:
        return {"result_type": "number", "value": rows[0][0], "row_count": 1, "sql": scoped}
    out = []
    for r in rows[:300]:
        mapping = getattr(r, "_mapping", None)
        if mapping is not None:
            out.append(dict(mapping))
        else:
            out.append(dict(r))
    return {"result_type": "table", "rows": out, "row_count": len(rows), "sql": scoped}


def _run_step_anomaly_scan(execution_output: Dict[str, Any]):
    if not execution_output:
        return {"anomalies": [], "count": 0}
    anomalies = []
    if execution_output.get("result_type") == "table":
        rows = execution_output.get("rows", [])
        if rows and isinstance(rows[0], dict):
            numeric_cols = [k for k, v in rows[0].items() if isinstance(v, (int, float))]
            for col in numeric_cols[:4]:
                vals = [float(r.get(col, 0) or 0) for r in rows if isinstance(r.get(col), (int, float))]
                if len(vals) < 5:
                    continue
                avg = sum(vals) / len(vals)
                if avg == 0:
                    continue
                max_v = max(vals)
                if max_v > avg * 2.5:
                    anomalies.append({"column": col, "type": "spike", "max": max_v, "avg": round(avg, 4)})
    return {"anomalies": anomalies, "count": len(anomalies)}


def _run_step_summary_writer(goal_text: str, step_outputs: Dict[str, Any], profile: Optional[AgentUserProfile]):
    exec_out = step_outputs.get("sql_execution", {})
    anomaly_out = step_outputs.get("anomaly_scan", {})
    style = profile.response_style if profile else "concise"
    base = []
    base.append(f"Goal: {goal_text}")
    if exec_out.get("result_type") == "number":
        base.append(f"Result: {exec_out.get('value')}")
    elif exec_out.get("result_type") == "table":
        base.append(f"Rows returned: {exec_out.get('row_count')}")
    if anomaly_out.get("count"):
        base.append(f"Anomalies found: {anomaly_out.get('count')}")
    summary = " | ".join(base)
    if style == "detailed":
        summary += ". Steps executed: " + ", ".join([k for k in step_outputs.keys()])
    return {"summary": summary}


def _pending_steps(db: Session, goal_id: UUID) -> List[AgentPlanStep]:
    return db.query(AgentPlanStep).filter(
        AgentPlanStep.goal_id == goal_id,
        AgentPlanStep.status.in_(["pending", "blocked"]),
    ).order_by(AgentPlanStep.step_order.asc()).all()


def execute_goal(
    db: Session,
    goal_id: UUID,
    auto_approve: bool = False,
    max_steps: int = 20,
    approval_token: Optional[str] = None,
) -> Dict[str, Any]:
    goal = db.query(AgentGoal).filter(AgentGoal.goal_id == goal_id).first()
    if not goal:
        raise ValueError("goal_not_found")
    active_plugin = ensure_active_plugin(goal.plugin_id)
    profile = get_or_create_profile(db, goal.user_id, goal.plugin_id) if goal.user_id else None
    goal.status = "in_progress"
    goal.updated_at = datetime.utcnow()
    db.commit()

    step_outputs: Dict[str, Any] = (goal.working_memory or {}).get("step_outputs", {})
    question = (goal.working_memory or {}).get("focus_question") or goal.goal_text
    executed_count = 0
    for step in _pending_steps(db, goal.goal_id):
        if executed_count >= max_steps:
            break
        if step.status == "blocked":
            if approval_token and goal.approval_token and approval_token == goal.approval_token:
                step.status = "pending"
                goal.requires_human_approval = False
                goal.approval_token = None
                goal.status = "in_progress"
                db.commit()
            else:
                continue

        step.status = "running"
        step.updated_at = datetime.utcnow()
        db.commit()

        try:
            if step.tool_name == "schema_retrieval":
                out = _run_step_schema_retrieval(active_plugin, question, goal.dataset_id, db)
            elif step.tool_name == "kb_retrieval":
                out = _run_step_kb_retrieval(active_plugin, question, goal.dataset_id, db)
            elif step.tool_name == "example_retrieval":
                out = _run_step_example_retrieval(active_plugin, question, goal.dataset_id, db)
            elif step.tool_name == "sql_generation":
                out = _run_step_sql_generation(active_plugin, question, goal.dataset_id, db, step_outputs)
            elif step.tool_name == "sql_verifier":
                sql = (step_outputs.get("sql_generation") or {}).get("sql")
                if not sql:
                    raise ValueError("missing_sql_for_verification")
                out = _run_step_sql_verifier(active_plugin, question, sql)
                if out.get("corrected_sql"):
                    sg = step_outputs.get("sql_generation") or {}
                    sg["sql"] = out["corrected_sql"]
                    step_outputs["sql_generation"] = sg
            elif step.tool_name == "sql_execution":
                sql = (step_outputs.get("sql_generation") or {}).get("sql")
                if not sql:
                    raise ValueError("missing_sql_for_execution")
                out = _run_step_sql_execution(active_plugin, sql, goal.dataset_id, db, auto_approve=auto_approve)
                if out.get("requires_approval"):
                    step.status = "blocked"
                    step.requires_approval = True
                    step.output_payload = out
                    goal.status = "waiting_approval"
                    goal.requires_human_approval = True
                    goal.approval_token = out.get("approval_token")
                    goal.updated_at = datetime.utcnow()
                    db.commit()
                    break
            elif step.tool_name == "anomaly_scan":
                out = _run_step_anomaly_scan(step_outputs.get("sql_execution", {}))
            elif step.tool_name == "summary_writer":
                out = _run_step_summary_writer(goal.goal_text, step_outputs, profile)
            else:
                out = {"message": f"unknown tool: {step.tool_name}"}

            step.status = "completed"
            step.output_payload = out
            step.updated_at = datetime.utcnow()
            step_outputs[step.tool_name] = out
            executed_count += 1
            db.commit()
        except Exception as e:
            step.status = "failed"
            step.error = str(e)
            step.updated_at = datetime.utcnow()
            goal.status = "failed"
            goal.updated_at = datetime.utcnow()
            db.commit()
            break

    # Finalize goal status
    steps = db.query(AgentPlanStep).filter(AgentPlanStep.goal_id == goal.goal_id).all()
    if all(s.status in {"completed", "skipped"} for s in steps):
        goal.status = "completed"
        goal.completed_at = datetime.utcnow()
        summary = (step_outputs.get("summary_writer") or {}).get("summary")
        goal.result_summary = summary
        # learning loop: promote successful SQL as example
        sql = (step_outputs.get("sql_generation") or {}).get("sql")
        if sql:
            store_rag_example(
                db,
                plugin_id=goal.plugin_id,
                dataset_id=goal.dataset_id,
                question=goal.goal_text,
                rewritten_question=question,
                sql=sql,
                answer_summary=summary or "Agent-completed analysis",
                quality_score=0.9,
                source="agent_success",
            )
    elif goal.status not in {"waiting_approval", "failed"}:
        goal.status = "in_progress"

    goal.working_memory = {"focus_question": question, "step_outputs": step_outputs}
    goal.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(goal)
    return {
        "goal_id": str(goal.goal_id),
        "status": goal.status,
        "requires_human_approval": bool(goal.requires_human_approval),
        "approval_token": goal.approval_token if goal.requires_human_approval else None,
        "result_summary": goal.result_summary,
        "executed_steps": executed_count,
        "step_outputs": step_outputs,
    }


def _safe_div(num: int, den: int) -> float:
    return round(num / den, 4) if den else 0.0


def compute_agent_metrics(
    db: Session,
    plugin_id: Optional[str] = None,
    days: int = 30,
) -> Dict[str, Any]:
    cutoff = datetime.utcnow() - timedelta(days=days)
    qh = db.query(QueryHistoryEntry).filter(QueryHistoryEntry.created_at >= cutoff)
    fb = db.query(QueryFeedback).filter(QueryFeedback.created_at >= cutoff)
    goals = db.query(AgentGoal).filter(AgentGoal.created_at >= cutoff)
    reviews = db.query(AgentGoal).filter(
        AgentGoal.created_at >= cutoff,
        AgentGoal.status == "waiting_approval",
    )
    if plugin_id:
        qh = qh.filter(QueryHistoryEntry.plugin_id == plugin_id)
        fb = fb.filter(QueryFeedback.plugin_id == plugin_id)
        goals = goals.filter(AgentGoal.plugin_id == plugin_id)
        reviews = reviews.filter(AgentGoal.plugin_id == plugin_id)

    history_rows = qh.all()
    feedback_rows = fb.all()
    goal_rows = goals.all()
    waiting_reviews = reviews.count()

    high_conf = sum(1 for r in history_rows if (r.confidence or "").lower() == "high")
    clarification_rate = _safe_div(
        sum(1 for r in history_rows if "clarification" in (r.answer_summary or "").lower()),
        len(history_rows),
    )
    correction_rate = _safe_div(sum(1 for r in feedback_rows if r.corrected_sql), len(history_rows))
    completed_goals = sum(1 for g in goal_rows if g.status == "completed")
    failed_goals = sum(1 for g in goal_rows if g.status == "failed")

    # first-answer accuracy proxy: high confidence and no negative feedback
    negatives = sum(1 for r in feedback_rows if int(r.rating or 0) == -1)
    first_answer_accuracy = _safe_div(max(0, high_conf - negatives), len(history_rows))
    human_handoff_rate = _safe_div(waiting_reviews, len(goal_rows))

    return {
        "period_days": days,
        "queries": len(history_rows),
        "feedback_items": len(feedback_rows),
        "goals_total": len(goal_rows),
        "goals_completed": completed_goals,
        "goals_failed": failed_goals,
        "first_answer_accuracy_proxy": first_answer_accuracy,
        "clarification_rate": clarification_rate,
        "correction_rate": correction_rate,
        "human_handoff_rate": human_handoff_rate,
    }


def create_automation(
    db: Session,
    plugin_id: str,
    dataset_id: Optional[str],
    user_id: Optional[str],
    title: str,
    goal_text: str,
    task_type: str = "monitor",
    schedule_cron: str = "0 8 * * *",
    config: Optional[dict] = None,
) -> AgentAutomation:
    row = AgentAutomation(
        plugin_id=plugin_id,
        dataset_id=dataset_id,
        user_id=user_id,
        title=title,
        goal_text=goal_text,
        task_type=task_type,
        schedule_cron=schedule_cron,
        config=config or {},
        updated_at=datetime.utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
