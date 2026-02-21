"""Decision quality evaluation: score a Decision artifact without any model calls."""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import duckdb

from backend.app.core.logging import get_logger
from backend.app.models.decisions import Action, Decision
from backend.app.models.reports import AnalystReport

logger = get_logger(__name__)


@dataclass
class ActionScore:
    action_type: str
    description_snippet: str
    has_stock_code_or_category: bool    # action targets a specific product or group
    rationale_references_kpi: bool      # rationale or description mentions a known KPI
    score: float                         # 0.0-1.0 for this action


@dataclass
class DecisionEvalResult:
    run_id: str
    total_actions: int
    overall_score: float                 # weighted 0.0-1.0
    has_rationale: bool
    has_kpi_references: bool
    has_forecast_references: bool
    confidence: float
    confidence_flag: str                 # "ok" | "suspiciously_high" | "suspiciously_low"
    action_scores: list[ActionScore] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)


def _load_artifact(run_id: str, artifact_type: str, duckdb_path: str) -> dict | None:
    """Load a single artifact JSON from run_artifacts. Returns None if not found."""
    conn = duckdb.connect(duckdb_path, read_only=True)
    try:
        rows = conn.execute(
            """
            SELECT artifact_json FROM run_artifacts
            WHERE run_id = ? AND artifact_type = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            [run_id, artifact_type],
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return None
    raw = rows[0][0]
    return json.loads(raw) if isinstance(raw, str) else raw


def _score_action(
    action: Action,
    kpi_names: set[str],
    rationale: str,
) -> ActionScore:
    """
    Score a single Action on two binary criteria (each worth 0.5):
    1. Has a stock_code or category — action targets something specific.
    2. Rationale or description references at least one known KPI name.
    """
    has_target = bool(action.stock_code or action.category)

    combined = (rationale + " " + action.description).lower()
    refs_kpi = (
        any(
            name.lower().replace("_", " ") in combined or name.lower() in combined
            for name in kpi_names
        )
        if kpi_names
        else bool(action.description.strip())
    )

    score = (0.5 if has_target else 0.0) + (0.5 if refs_kpi else 0.0)

    return ActionScore(
        action_type=action.action_type,
        description_snippet=action.description[:80],
        has_stock_code_or_category=has_target,
        rationale_references_kpi=refs_kpi,
        score=score,
    )


def run_decision_eval(run_id: str, duckdb_path: str) -> DecisionEvalResult:
    """
    Load a Decision artifact and score its quality across five dimensions:

    Scoring weights:
      - Rationale present (non-trivial, > 20 chars):  0.20
      - KPI references present:                        0.20
      - Forecast references present:                   0.10
      - Confidence in reasonable range (0.4-0.95):     0.10
      - Average per-action score:                      0.40

    Per-action score (0-1): 0.5 if has stock_code/category + 0.5 if mentions a KPI.

    Returns DecisionEvalResult with overall score (0-1), confidence flag, and findings.
    """
    logger.info("decision_eval.start", run_id=run_id)

    decision_data = _load_artifact(run_id, "decision", duckdb_path)
    if decision_data is None:
        raise ValueError(f"No decision artifact found for run_id={run_id}")
    decision = Decision.model_validate(decision_data)

    # Load analyst report to validate KPI reference names
    analyst_data = _load_artifact(run_id, "analyst_report", duckdb_path)
    kpi_names: set[str] = set()
    if analyst_data is not None:
        try:
            analyst = AnalystReport.model_validate(analyst_data)
            kpi_names = {kpi.name for kpi in analyst.kpis}
        except Exception:
            pass

    findings: list[str] = []

    # --- Decision-level checks ---
    has_rationale = bool(decision.rationale.strip()) and len(decision.rationale.strip()) > 20
    if not has_rationale:
        findings.append("Decision rationale is absent or too short (< 20 chars).")

    has_kpi_refs = bool(decision.kpi_references)
    if not has_kpi_refs:
        findings.append("Decision has no kpi_references — KPI grounding cannot be verified.")

    has_forecast_refs = bool(decision.forecast_references)
    if not has_forecast_refs:
        findings.append("Decision has no forecast_references.")

    # Validate that referenced KPIs exist in the analyst report
    if kpi_names and has_kpi_refs:
        unknown = [r for r in decision.kpi_references if r not in kpi_names]
        if unknown:
            findings.append(f"KPI references not found in analyst report: {unknown}")

    confidence = decision.confidence
    if confidence >= 0.99:
        confidence_flag = "suspiciously_high"
        findings.append(
            f"Confidence is {confidence:.2f} — suspiciously high. "
            "Manager should express uncertainty."
        )
    elif confidence < 0.2:
        confidence_flag = "suspiciously_low"
        findings.append(f"Confidence is {confidence:.2f} — suspiciously low.")
    else:
        confidence_flag = "ok"

    if not decision.actions:
        findings.append("Decision has no actions.")

    # --- Per-action scoring ---
    action_scores: list[ActionScore] = []
    for action in decision.actions:
        s = _score_action(action, kpi_names, decision.rationale)
        action_scores.append(s)
        if not s.has_stock_code_or_category:
            findings.append(
                f"Action '{action.action_type}' has no stock_code or category — too vague."
            )

    # --- Weighted overall score ---
    c_rationale = 1.0 if has_rationale else 0.0
    c_kpi_refs = 1.0 if has_kpi_refs else 0.0
    c_forecast_refs = 1.0 if has_forecast_refs else 0.0
    c_confidence = 1.0 if confidence_flag == "ok" else 0.0
    c_actions = (
        sum(s.score for s in action_scores) / len(action_scores)
        if action_scores else 0.0
    )

    overall_score = round(
        0.20 * c_rationale
        + 0.20 * c_kpi_refs
        + 0.10 * c_forecast_refs
        + 0.10 * c_confidence
        + 0.40 * c_actions,
        3,
    )

    result = DecisionEvalResult(
        run_id=run_id,
        total_actions=len(decision.actions),
        overall_score=overall_score,
        has_rationale=has_rationale,
        has_kpi_references=has_kpi_refs,
        has_forecast_references=has_forecast_refs,
        confidence=confidence,
        confidence_flag=confidence_flag,
        action_scores=action_scores,
        findings=findings,
    )

    logger.info("decision_eval.done", run_id=run_id, score=overall_score, num_findings=len(findings))
    return result
