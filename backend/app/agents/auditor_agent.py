"""AuditorAgent — verifies factuality, grounding, and schema validity."""

from __future__ import annotations

import json

from backend.app.agents.base import build_llm, call_with_repair, load_prompt
from backend.app.core.config import Settings, get_settings
from backend.app.core.logging import get_logger
from backend.app.models.audit import AuditFinding, AuditReport, AuditReportDraft
from backend.app.models.decisions import Decision
from backend.app.models.reports import AnalystReport, ForecastReport
from backend.app.models.run_context import RunContext
from backend.app.tools.sql_tool import SQLTool

logger = get_logger(__name__)


def _build_audit_context(
    analyst_report: AnalystReport,
    forecast_report: ForecastReport,
    decision: Decision,
) -> str:
    """Build a compact, complete audit context — no truncation by character count."""
    lines = ["=== ANALYST REPORT ==="]
    lines.append(f"Period: {analyst_report.period_start} → {analyst_report.period_end} | Mode: {analyst_report.mode}")
    lines.append("\nKPIs (grounded — verify values match SQL evidence below):")
    for kpi in analyst_report.kpis:
        sql_ref = kpi.evidence.sql.strip().splitlines()[0] if kpi.evidence else "NO EVIDENCE"
        lines.append(f"  {kpi.name}: {kpi.value} {kpi.unit}  [SQL: {sql_ref}]")

    lines.append("\nTop SKUs by revenue:")
    for r in analyst_report.top_skus[:10]:
        lines.append(f"  {r.get('stock_code')} {r.get('description','')}: £{r.get('total_revenue',0):.2f} ({r.get('total_units',0)} units)")

    lines.append("\nBottom SKUs by revenue:")
    for r in analyst_report.bottom_skus[:10]:
        lines.append(f"  {r.get('stock_code')} {r.get('description','')}: £{r.get('total_revenue',0):.2f}")

    lines.append("\nAnomalies:")
    for a in analyst_report.anomalies:
        lines.append(f"  [{a.severity.upper()}] {a.description}")

    lines.append(f"\nNarrative: {analyst_report.narrative}")

    lines.append("\nSQL Evidence queries:")
    for ev in analyst_report.queries_executed:
        lines.append(f"  Query: {ev.sql.strip()}")
        if ev.result_preview:
            lines.append(f"  Result preview: {ev.result_preview[:2]}")

    lines.append("\n=== FORECAST REPORT ===")
    lines.append(f"Model: {forecast_report.model_name} | Horizon: {forecast_report.horizon_days} days")
    lines.append("\nBacktest metrics:")
    for bm in forecast_report.backtest_metrics:
        mape = f"{bm.mape:.1%}" if bm.mape is not None else "N/A"
        rmse = f"{bm.rmse:.2f}" if bm.rmse is not None else "N/A"
        lines.append(f"  {bm.stock_code}: MAPE={mape}, RMSE={rmse}, train={bm.train_start}→{bm.train_end}")

    lines.append(f"\nForecast rows ({len(forecast_report.forecasts)} total — first 14 shown):")
    for row in forecast_report.forecasts[:14]:
        lines.append(f"  {row.stock_code} {row.ds}: yhat={row.yhat}, lower={row.yhat_lower}, upper={row.yhat_upper}")

    lines.append("\n=== MANAGER DECISION ===")
    lines.append(f"Confidence: {decision.confidence} | Rationale: {decision.rationale}")
    lines.append("\nActions:")
    for a in decision.actions:
        lines.append(f"  [{a.urgency.upper()}] {a.action_type} SKU={a.stock_code}: {a.description}")
        if a.expected_impact:
            lines.append(f"    Impact: {a.expected_impact}")

    lines.append(f"\nKPI references: {decision.kpi_references}")
    lines.append(f"Forecast references: {decision.forecast_references}")
    lines.append(f"Risks: {decision.risks}")

    return "\n".join(lines)


class AuditorAgent:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.llm = build_llm(self.settings)

    def run(
        self,
        ctx: RunContext,
        analyst_report: AnalystReport,
        forecast_report: ForecastReport,
        decision: Decision,
    ) -> AuditReport:
        logger.info("auditor_agent.start", run_id=ctx.run_id)

        findings: list[AuditFinding] = []

        # --- Deterministic checks (no LLM needed) ---
        findings += self._check_kpi_citations(ctx, analyst_report)
        findings += self._check_bounded_mode(ctx, analyst_report)
        findings += self._check_decision_references(ctx, decision, analyst_report)

        # --- LLM-assisted checks ---
        prompt = load_prompt("auditor")
        audit_context = _build_audit_context(analyst_report, forecast_report, decision)
        user_msg = prompt["user"].format(
            run_id=ctx.run_id,
            audit_context=audit_context,
            mode=ctx.mode,
            as_of_date=ctx.as_of_date,
        )

        llm_audit = call_with_repair(
            self.llm,
            prompt["system"],
            user_msg,
            AuditReportDraft,
            max_retries=self.settings.max_repair_retries,
        )
        # Inject run metadata that the LLM is not expected to produce
        findings += [
            AuditFinding(
                run_id=ctx.run_id,
                as_of_date=ctx.as_of_date,
                **f.model_dump(),
            )
            for f in llm_audit.findings
        ]

        report = AuditReport(
            run_id=ctx.run_id,
            as_of_date=ctx.as_of_date,
            mode=ctx.mode,
            findings=findings,
            summary=llm_audit.summary,
        )

        logger.info(
            "auditor_agent.done",
            run_id=ctx.run_id,
            num_findings=len(findings),
            passed=report.passed,
        )
        return report

    def _check_kpi_citations(self, ctx: RunContext, report: AnalystReport) -> list[AuditFinding]:
        """Every KPI must have a query_evidence."""
        findings = []
        for kpi in report.kpis:
            if kpi.evidence is None:
                findings.append(AuditFinding(
                    run_id=ctx.run_id,
                    as_of_date=ctx.as_of_date,
                    severity="warning",
                    finding_type="missing_citation",
                    description=f"KPI '{kpi.name}' has no SQL evidence attached.",
                    affected_field=f"kpis[{kpi.name}].evidence",
                ))
        return findings

    def _check_bounded_mode(self, ctx: RunContext, report: AnalystReport) -> list[AuditFinding]:
        """In bounded mode, verify period_end does not exceed as_of_date."""
        findings = []
        if ctx.mode == "bounded" and report.period_end > ctx.as_of_date:
            findings.append(AuditFinding(
                run_id=ctx.run_id,
                as_of_date=ctx.as_of_date,
                severity="error",
                finding_type="policy_violation",
                description=(
                    f"Analyst report period_end {report.period_end} "
                    f"exceeds as_of_date {ctx.as_of_date} in bounded mode."
                ),
                affected_field="period_end",
                reported_value=str(report.period_end),
                verified_value=str(ctx.as_of_date),
            ))
        return findings

    def _check_decision_references(
        self, ctx: RunContext, decision: Decision, analyst_report: AnalystReport
    ) -> list[AuditFinding]:
        """Decision must have non-empty rationale."""
        findings = []
        if not decision.rationale.strip():
            findings.append(AuditFinding(
                run_id=ctx.run_id,
                as_of_date=ctx.as_of_date,
                severity="warning",
                finding_type="missing_citation",
                description="Manager decision has no rationale.",
                affected_field="rationale",
            ))
        if not decision.actions:
            findings.append(AuditFinding(
                run_id=ctx.run_id,
                as_of_date=ctx.as_of_date,
                severity="error",
                finding_type="other",
                description="Manager decision has no actions.",
                affected_field="actions",
            ))
        return findings
