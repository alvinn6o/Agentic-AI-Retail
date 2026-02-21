"""LangGraph workflow state schema."""

from __future__ import annotations

from typing import Annotated, Any

from langgraph.graph import add_messages
from pydantic import BaseModel

from backend.app.models.audit import AuditReport
from backend.app.models.decisions import Decision, WorkerTask
from backend.app.models.reports import AnalystReport, ForecastReport
from backend.app.models.run_context import RunContext


class WorkflowState(BaseModel):
    """Immutable-ish state passed between LangGraph nodes."""

    ctx: RunContext

    # Filled progressively as workflow advances
    de_summary: dict[str, Any] | None = None
    analyst_report: AnalystReport | None = None
    forecast_report: ForecastReport | None = None
    decision: Decision | None = None
    worker_tasks: list[WorkerTask] | None = None
    audit_report: AuditReport | None = None

    # Errors
    errors: list[str] | None = None

    class Config:
        arbitrary_types_allowed = True
