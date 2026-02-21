"""Factuality evaluation: re-execute KPI SQL and compare against stored values."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import duckdb

from backend.app.core.logging import get_logger
from backend.app.models.reports import AnalystReport, KPI

logger = get_logger(__name__)


@dataclass
class KPIMismatch:
    kpi_name: str
    stored_value: float
    recomputed_value: float
    relative_error: float   # abs(stored - recomputed) / max(abs(recomputed), 1e-9)
    sql: str
    params: list[Any]


@dataclass
class FactualityResult:
    run_id: str
    total_kpis: int
    kpis_with_evidence: int
    kpis_verified: int              # recomputed value matched within tolerance
    kpis_mismatched: int
    kpis_no_evidence: int
    factuality_score: float         # kpis_verified / kpis_with_evidence (0-1), 1.0 if no evidence
    mismatches: list[KPIMismatch] = field(default_factory=list)
    narrative_numbers_not_in_kpis: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _load_analyst_report(run_id: str, duckdb_path: str) -> AnalystReport:
    """Load an AnalystReport artifact from the run_artifacts table."""
    conn = duckdb.connect(duckdb_path, read_only=True)
    try:
        rows = conn.execute(
            """
            SELECT artifact_json FROM run_artifacts
            WHERE run_id = ? AND artifact_type = 'analyst_report'
            ORDER BY created_at DESC LIMIT 1
            """,
            [run_id],
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        raise ValueError(f"No analyst_report artifact found for run_id={run_id}")

    raw = rows[0][0]
    data = json.loads(raw) if isinstance(raw, str) else raw
    return AnalystReport.model_validate(data)


def _reexecute_kpi_sql(kpi: KPI, duckdb_path: str) -> float | None:
    """
    Re-execute the SQL stored in kpi.evidence and extract the first numeric value
    from the first result row. Returns None if execution fails or result is empty.
    """
    if kpi.evidence is None:
        return None

    conn = duckdb.connect(duckdb_path, read_only=True)
    try:
        result = conn.execute(kpi.evidence.sql, kpi.evidence.params or [])
        columns = [desc[0] for desc in result.description]
        rows = result.fetchall()
    except Exception as exc:
        logger.warning("factuality_eval.sql_error", kpi=kpi.name, error=str(exc))
        return None
    finally:
        conn.close()

    if not rows:
        return None

    # Return the first numeric value found in the first row
    row = dict(zip(columns, rows[0]))
    for val in row.values():
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return None


def _extract_numbers_from_narrative(narrative: str) -> list[str]:
    """Extract all numeric tokens (with optional currency/percent) from text."""
    return re.findall(r"[£$€]?\d[\d,]*\.?\d*%?", narrative)


def _normalize_number(token: str) -> float | None:
    """Strip non-numeric characters and parse to float."""
    cleaned = re.sub(r"[£$€,%]", "", token).replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def run_factuality_eval(
    run_id: str,
    duckdb_path: str,
    tolerance: float = 0.01,    # 1% relative error allowed for floating point
) -> FactualityResult:
    """
    Load an AnalystReport, re-execute each KPI's SQL, and compare values.

    For each KPI with QueryEvidence:
    - Re-executes the stored SQL with the stored params against the warehouse.
    - Compares the recomputed value to the stored value using relative error.
    - KPIs within `tolerance` are marked verified; others go into mismatches.

    Also extracts numbers from the narrative and flags any that do not appear
    in the set of KPI values (potential unsupported claims).

    Args:
        run_id: The run UUID to evaluate.
        duckdb_path: Path to the DuckDB warehouse file.
        tolerance: Max allowed relative error (default 1%).

    Returns:
        FactualityResult with per-KPI breakdown and overall factuality score.
    """
    logger.info("factuality_eval.start", run_id=run_id)
    report = _load_analyst_report(run_id, duckdb_path)

    mismatches: list[KPIMismatch] = []
    warnings: list[str] = []
    kpis_verified = 0
    kpis_with_evidence = 0

    for kpi in report.kpis:
        if kpi.evidence is None:
            warnings.append(f"KPI '{kpi.name}' has no QueryEvidence — cannot verify.")
            continue

        kpis_with_evidence += 1
        recomputed = _reexecute_kpi_sql(kpi, duckdb_path)

        if recomputed is None:
            warnings.append(f"KPI '{kpi.name}': SQL re-execution returned no result or failed.")
            continue

        rel_error = abs(kpi.value - recomputed) / max(abs(recomputed), 1e-9)

        if rel_error <= tolerance:
            kpis_verified += 1
            logger.info(
                "factuality_eval.kpi_ok",
                kpi=kpi.name,
                stored=kpi.value,
                recomputed=recomputed,
                rel_error=round(rel_error, 6),
            )
        else:
            mismatches.append(KPIMismatch(
                kpi_name=kpi.name,
                stored_value=kpi.value,
                recomputed_value=recomputed,
                relative_error=rel_error,
                sql=kpi.evidence.sql,
                params=kpi.evidence.params or [],
            ))
            logger.warning(
                "factuality_eval.kpi_mismatch",
                kpi=kpi.name,
                stored=kpi.value,
                recomputed=recomputed,
                rel_error=round(rel_error, 4),
            )

    # Check narrative for numbers not traceable to any KPI value
    kpi_values: set[float] = {round(k.value, 2) for k in report.kpis}
    narrative_numbers_not_in_kpis: list[str] = []
    for token in _extract_numbers_from_narrative(report.narrative):
        num = _normalize_number(token)
        if num is None:
            continue
        if not any(abs(round(num, 2) - kv) / max(abs(kv), 1e-9) < 0.01 for kv in kpi_values):
            narrative_numbers_not_in_kpis.append(token)

    factuality_score = kpis_verified / kpis_with_evidence if kpis_with_evidence > 0 else 1.0

    result = FactualityResult(
        run_id=run_id,
        total_kpis=len(report.kpis),
        kpis_with_evidence=kpis_with_evidence,
        kpis_verified=kpis_verified,
        kpis_mismatched=len(mismatches),
        kpis_no_evidence=len(report.kpis) - kpis_with_evidence,
        factuality_score=factuality_score,
        mismatches=mismatches,
        narrative_numbers_not_in_kpis=narrative_numbers_not_in_kpis,
        warnings=warnings,
    )

    logger.info(
        "factuality_eval.done",
        run_id=run_id,
        score=round(factuality_score, 3),
        mismatches=len(mismatches),
        narrative_anomalies=len(narrative_numbers_not_in_kpis),
    )
    return result
