"""Typed schema for auditor findings."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


_VALID_FINDING_TYPES = {
    "number_mismatch", "missing_citation", "hallucinated_metric",
    "policy_violation", "schema_drift", "other",
}


class AuditFindingDraft(BaseModel):
    """Slim schema for LLM parsing — run metadata is injected by the agent afterward."""
    severity: Literal["info", "warning", "error"] = "info"
    finding_type: str = "other"   # accepts any string; normalised by validator
    description: str = ""
    affected_field: str = ""
    reported_value: str = ""
    verified_value: str = ""
    recommendation: str = ""

    @field_validator("finding_type", mode="before")
    @classmethod
    def normalise_finding_type(cls, v: Any) -> str:
        if isinstance(v, str) and v in _VALID_FINDING_TYPES:
            return v
        return "other"

    @field_validator("reported_value", "verified_value", mode="before")
    @classmethod
    def coerce_to_str(cls, v: Any) -> str:
        if v is None:
            return ""
        return str(v)


class AuditReportDraft(BaseModel):
    """Slim schema for LLM parsing — run metadata is injected by the agent afterward."""
    findings: list[AuditFindingDraft] = Field(default_factory=list)
    summary: str = ""


class AuditFinding(BaseModel):
    run_id: str
    as_of_date: date
    severity: Literal["info", "warning", "error"]
    finding_type: Literal[
        "number_mismatch",
        "missing_citation",
        "hallucinated_metric",
        "policy_violation",
        "schema_drift",
        "other",
    ]
    description: str
    affected_field: str = ""
    reported_value: str = ""
    verified_value: str = ""
    recommendation: str = ""


class AuditReport(BaseModel):
    run_id: str
    as_of_date: date
    mode: str
    findings: list[AuditFinding] = Field(default_factory=list)
    passed: bool = True
    summary: str = ""

    def model_post_init(self, __context: object) -> None:
        errors = [f for f in self.findings if f.severity == "error"]
        object.__setattr__(self, "passed", len(errors) == 0)
