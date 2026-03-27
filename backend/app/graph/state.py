"""LangGraph workflow state schema."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from backend.app.models.audit import AuditReport
from backend.app.models.controls import ControlReviewReport
from backend.app.models.decisions import Decision, WorkerTask
from backend.app.models.integration import DispatchReport
from backend.app.models.reports import AnalystReport, ForecastReport
from backend.app.models.run_context import RunContext


class WorkflowState(BaseModel):
    """Immutable-ish state passed between LangGraph nodes."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    ctx: RunContext

    # Filled progressively as workflow advances
    de_summary: dict[str, Any] | None = None
    analyst_report: AnalystReport | None = None
    forecast_report: ForecastReport | None = None
    decision: Decision | None = None
    control_review: ControlReviewReport | None = None
    worker_tasks: list[WorkerTask] | None = None
    audit_report: AuditReport | None = None
    dispatch_report: DispatchReport | None = None

    # Errors
    errors: list[str] | None = None
