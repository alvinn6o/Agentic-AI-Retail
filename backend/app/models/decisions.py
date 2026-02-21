"""Typed schemas for manager decisions and worker tasks."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class Action(BaseModel):
    action_type: Literal["restock", "markdown", "reorder", "promo", "staffing", "audit_returns", "other"]
    stock_code: str | None = None
    category: str | None = None
    description: str
    quantity: float | None = None
    urgency: Literal["low", "medium", "high"] = "medium"
    expected_impact: str = ""

    @field_validator("quantity", mode="before")
    @classmethod
    def coerce_quantity(cls, v: Any) -> float | None:
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None


class DecisionDraft(BaseModel):
    """Slim schema for LLM parsing — excludes run metadata filled in by the agent."""
    actions: list[Action] = Field(default_factory=list)
    rationale: str = ""
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    risks: list[str] = Field(default_factory=list)
    kpi_references: list[str] = Field(default_factory=list)
    forecast_references: list[str] = Field(default_factory=list)


class Decision(BaseModel):
    run_id: str
    as_of_date: date
    mode: str
    actions: list[Action] = Field(default_factory=list)
    rationale: str
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    risks: list[str] = Field(default_factory=list)
    kpi_references: list[str] = Field(default_factory=list)   # references to AnalystReport KPI names
    forecast_references: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Worker Tasks
# ---------------------------------------------------------------------------

class ChecklistItem(BaseModel):
    step: str
    completed: bool = False


class WorkerTask(BaseModel):
    # run_id and task_id are set by WorkerAgent after parsing — defaults allow LLM output to omit them.
    run_id: str = ""
    task_id: str = ""
    assigned_to: str = ""              # e.g. "warehouse_team", "marketing_team"
    action_type: str
    title: str
    description: str
    due_date: str = ""
    priority: Literal["low", "medium", "high"] = "medium"
    checklist: list[ChecklistItem] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    expected_outcome: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("acceptance_criteria", mode="before")
    @classmethod
    def coerce_str_to_list(cls, v: Any) -> Any:
        if isinstance(v, str):
            return [v]
        return v
