"""Typed schemas for deterministic workflow controls and approval gates."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class PolicyCitation(BaseModel):
    source: str
    control_id: str
    summary: str


class ActionControlReview(BaseModel):
    action_index: int
    action_type: str
    stock_code: str | None = None
    category: str | None = None
    description: str = ""
    control_family: Literal["inventory", "pricing", "operations", "quality", "manual_review"]
    risk_tier: Literal["low", "medium", "high", "critical"]
    approval_role: Literal[
        "none",
        "warehouse_manager",
        "category_manager",
        "operations_manager",
        "director",
        "quality_manager",
        "manual_review_board",
    ] = "none"
    execution_state: Literal["auto_release", "hold_for_approval", "blocked"]
    reasons: list[str] = Field(default_factory=list)
    policy_citations: list[PolicyCitation] = Field(default_factory=list)


class ControlReviewReport(BaseModel):
    run_id: str
    as_of_date: date
    mode: str
    control_profile: Literal["standard", "regulated"]
    overall_state: Literal["auto_release", "approval_required", "blocked"]
    summary: str = ""
    action_reviews: list[ActionControlReview] = Field(default_factory=list)
    auto_releasable_actions: list[int] = Field(default_factory=list)
    approval_required_actions: list[int] = Field(default_factory=list)
    blocked_actions: list[int] = Field(default_factory=list)
    requires_human_approval: bool = False
