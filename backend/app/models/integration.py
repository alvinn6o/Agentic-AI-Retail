"""Typed schemas for enterprise-system dispatch results."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field


class DispatchRecord(BaseModel):
    task_id: str
    assigned_to: str
    title: str
    target_system: str
    endpoint: str = ""
    status: Literal["prepared", "dry_run", "dispatched", "skipped", "blocked", "failed"]
    reason: str = ""
    external_id: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    response_body: dict[str, Any] = Field(default_factory=dict)


class DispatchReport(BaseModel):
    run_id: str
    as_of_date: date
    control_profile: Literal["standard", "regulated"]
    target_system: str
    status: Literal[
        "dry_run",
        "dispatched",
        "blocked",
        "approval_required",
        "skipped",
        "failed",
        "not_configured",
    ]
    summary: str = ""
    records: list[DispatchRecord] = Field(default_factory=list)
