"""LangGraph orchestration — the weekly business cycle workflow."""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

import duckdb
from langgraph.graph import END, StateGraph

from backend.app.agents.analyst_agent import AnalystAgent
from backend.app.agents.auditor_agent import AuditorAgent
from backend.app.agents.data_engineer_agent import DataEngineerAgent
from backend.app.agents.data_scientist_agent import DataScientistAgent
from backend.app.agents.manager_agent import ManagerAgent
from backend.app.agents.worker_agent import WorkerAgent
from backend.app.core.config import Settings, get_settings
from backend.app.core.logging import get_logger
from backend.app.graph.state import WorkflowState
from backend.app.models.run_context import RunContext

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Circuit-breaker routers
# Evaluated by LangGraph after each node; route to "persist" if a required
# upstream artifact is missing rather than letting downstream nodes fail.
# ---------------------------------------------------------------------------

def _route_after_parallel(state: WorkflowState) -> str:
    """After analyst + data_scientist fan-in: only proceed if both reports exist."""
    if state.analyst_report is None or state.forecast_report is None:
        return "persist"
    return "manager"


def _route_after_manager(state: WorkflowState) -> str:
    """Only run worker if manager produced a decision."""
    if state.decision is None:
        return "persist"
    return "worker"


def _route_after_worker(state: WorkflowState) -> str:
    """Only run auditor if worker produced tasks."""
    if not state.worker_tasks:
        return "persist"
    return "auditor"


# ---------------------------------------------------------------------------
# Node functions
# ---------------------------------------------------------------------------

def node_data_engineer(state: WorkflowState) -> dict[str, Any]:
    settings = get_settings()
    agent = DataEngineerAgent(settings)
    try:
        summary = agent.ingest(state.ctx)
        return {"de_summary": summary}
    except Exception as exc:
        logger.error("node.de.error", error=str(exc))
        return {"errors": (state.errors or []) + [f"DE: {exc}"]}


def node_analyst(state: WorkflowState) -> dict[str, Any]:
    settings = get_settings()
    agent = AnalystAgent(settings)
    ctx = state.ctx

    period_start = ctx.start_date
    period_end = ctx.as_of_date

    try:
        report = agent.run(ctx, period_start, period_end)
        return {"analyst_report": report}
    except Exception as exc:
        logger.error("node.analyst.error", error=str(exc))
        return {"errors": (state.errors or []) + [f"Analyst: {exc}"]}


def node_data_scientist(state: WorkflowState) -> dict[str, Any]:
    settings = get_settings()
    agent = DataScientistAgent(settings)
    try:
        report = agent.run(state.ctx, horizon_days=28)
        return {"forecast_report": report}
    except Exception as exc:
        logger.error("node.ds.error", error=str(exc))
        return {"errors": (state.errors or []) + [f"DS: {exc}"]}


def node_manager(state: WorkflowState) -> dict[str, Any]:
    # Precondition guaranteed by _route_after_parallel — both reports exist here.
    settings = get_settings()
    agent = ManagerAgent(settings)
    try:
        decision = agent.run(state.ctx, state.analyst_report, state.forecast_report)
        return {"decision": decision}
    except Exception as exc:
        logger.error("node.manager.error", error=str(exc))
        return {"errors": (state.errors or []) + [f"Manager: {exc}"]}


def node_worker(state: WorkflowState) -> dict[str, Any]:
    # Precondition guaranteed by _route_after_manager — decision exists here.
    settings = get_settings()
    agent = WorkerAgent(settings)
    try:
        tasks = agent.run(state.ctx, state.decision)
        return {"worker_tasks": tasks}
    except Exception as exc:
        logger.error("node.worker.error", error=str(exc))
        return {"errors": (state.errors or []) + [f"Worker: {exc}"]}


def node_auditor(state: WorkflowState) -> dict[str, Any]:
    # Precondition guaranteed by _route_after_worker — all artifacts exist here.
    settings = get_settings()
    agent = AuditorAgent(settings)
    try:
        audit = agent.run(
            state.ctx, state.analyst_report, state.forecast_report, state.decision
        )
        return {"audit_report": audit}
    except Exception as exc:
        logger.error("node.auditor.error", error=str(exc))
        return {"errors": (state.errors or []) + [f"Auditor: {exc}"]}


def node_fan_in(state: WorkflowState) -> dict[str, Any]:
    """No-op barrier — executed once after BOTH analyst and data_scientist have
    completed and written their reports into state.  Actual routing to manager
    or persist is handled by the conditional edge that follows this node."""
    return {}


def node_persist(state: WorkflowState) -> dict[str, Any]:
    """Persist all artifacts to DuckDB."""
    settings = get_settings()
    db_path = str(settings.duckdb_path)
    run_id = state.ctx.run_id

    try:
        conn = duckdb.connect(db_path)

        def persist_artifact(artifact_type: str, obj: Any) -> None:
            if obj is None:
                return
            payload = obj.model_dump_json() if hasattr(obj, "model_dump_json") else json.dumps(obj)
            conn.execute(
                "INSERT INTO run_artifacts (run_id, artifact_type, artifact_json) VALUES (?, ?, ?)",
                [run_id, artifact_type, payload],
            )

        persist_artifact("analyst_report", state.analyst_report)
        persist_artifact("forecast_report", state.forecast_report)
        persist_artifact("decision", state.decision)
        persist_artifact("audit_report", state.audit_report)

        if state.decision:
            conn.execute(
                "INSERT INTO decision_log (run_id, as_of_date, mode, decision_json) VALUES (?, ?, ?, ?)",
                [run_id, str(state.ctx.as_of_date), state.ctx.mode, state.decision.model_dump_json()],
            )

        if state.worker_tasks:
            for task in state.worker_tasks:
                conn.execute(
                    "INSERT INTO task_queue (run_id, task_json) VALUES (?, ?)",
                    [run_id, task.model_dump_json()],
                )
            # Also persist as a single artifact so the artifacts endpoint returns them
            tasks_payload = json.dumps([json.loads(t.model_dump_json()) for t in state.worker_tasks])
            conn.execute(
                "INSERT INTO run_artifacts (run_id, artifact_type, artifact_json) VALUES (?, ?, ?)",
                [run_id, "worker_tasks", tasks_payload],
            )

        conn.close()
        logger.info("persist.done", run_id=run_id)
    except Exception as exc:
        logger.error("persist.error", error=str(exc))
        return {"errors": (state.errors or []) + [f"Persist: {exc}"]}

    return {}


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_workflow() -> StateGraph:
    builder = StateGraph(WorkflowState)

    builder.add_node("data_engineer", node_data_engineer)
    builder.add_node("analyst", node_analyst)
    builder.add_node("data_scientist", node_data_scientist)
    builder.add_node("fan_in", node_fan_in)
    builder.add_node("manager", node_manager)
    builder.add_node("worker", node_worker)
    builder.add_node("auditor", node_auditor)
    builder.add_node("persist", node_persist)

    builder.set_entry_point("data_engineer")

    # DE → analyst + data_scientist in parallel
    builder.add_edge("data_engineer", "analyst")
    builder.add_edge("data_engineer", "data_scientist")

    # Fan-in barrier: LangGraph waits for ALL incoming edges before executing
    # fan_in, so this node only runs after both analyst AND data_scientist have
    # written their reports into state.  The conditional edge from fan_in then
    # evaluates _route_after_parallel exactly once with both outputs present.
    builder.add_edge("analyst", "fan_in")
    builder.add_edge("data_scientist", "fan_in")
    builder.add_conditional_edges(
        "fan_in",
        _route_after_parallel,
        {"manager": "manager", "persist": "persist"},
    )

    # manager → worker (or bypass to persist if no decision)
    builder.add_conditional_edges(
        "manager",
        _route_after_manager,
        {"worker": "worker", "persist": "persist"},
    )

    # worker → auditor (or bypass to persist if no tasks)
    builder.add_conditional_edges(
        "worker",
        _route_after_worker,
        {"auditor": "auditor", "persist": "persist"},
    )

    # auditor → persist → END
    builder.add_edge("auditor", "persist")
    builder.add_edge("persist", END)

    return builder


def run_cycle(
    as_of_date: date,
    mode: str,
    start_date: date | None = None,
    settings: Settings | None = None,
    skip_ingest: bool = False,
    run_id: str | None = None,
) -> WorkflowState:
    """Run a full business cycle and return final state."""
    ctx_kwargs: dict[str, Any] = {
        "start_date": start_date or as_of_date - timedelta(days=90),
        "as_of_date": as_of_date,
        "mode": mode,
    }
    if run_id is not None:
        ctx_kwargs["run_id"] = run_id
    ctx = RunContext(**ctx_kwargs)
    initial_state = WorkflowState(ctx=ctx)

    graph = build_workflow()

    if skip_ingest:
        # Remove DE node and start from analyst
        graph_compiled = graph.compile()
    else:
        graph_compiled = graph.compile()

    logger.info("workflow.start", run_id=ctx.run_id, mode=mode, as_of=str(as_of_date))
    final_state = graph_compiled.invoke(initial_state)
    logger.info("workflow.done", run_id=ctx.run_id)

    return final_state
