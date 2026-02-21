"""ManagerAgent — reads reports and issues business decisions."""

from __future__ import annotations

import json

from backend.app.agents.base import build_llm, call_with_repair, load_prompt
from backend.app.core.config import Settings, get_settings
from backend.app.core.logging import get_logger
from backend.app.models.decisions import Decision, DecisionDraft
from backend.app.models.reports import AnalystReport, ForecastReport
from backend.app.models.run_context import RunContext

logger = get_logger(__name__)


def _summarize_analyst(report: AnalystReport) -> str:
    lines = [f"Period: {report.period_start} to {report.period_end}", ""]
    for kpi in report.kpis:
        lines.append(f"  {kpi.name}: {kpi.value} {kpi.unit}")
    if report.top_skus:
        lines.append("\nTop SKUs by revenue:")
        for r in report.top_skus[:5]:
            lines.append(f"  {r.get('stock_code')}: £{r.get('total_revenue', 0):.2f}")
    if report.anomalies:
        lines.append("\nAnomalies:")
        for a in report.anomalies:
            lines.append(f"  [{a.severity}] {a.description}")
    return "\n".join(lines)


def _summarize_forecast(report: ForecastReport) -> str:
    """Build forecast summary with an explicit reliability verdict.

    When average MAPE > 100%, the LLM is instructed to treat the forecast
    as directional only and base decisions on analyst KPIs instead.
    """
    valid_mapes = [bm.mape for bm in report.backtest_metrics if bm.mape is not None]
    avg_mape = sum(valid_mapes) / len(valid_mapes) if valid_mapes else None
    reliable = avg_mape is not None and avg_mape <= 1.0  # ≤100% MAPE

    if reliable:
        verdict = f"RELIABLE (avg MAPE {avg_mape:.1%}) — specific forecast values may be referenced."
    elif avg_mape is not None:
        verdict = (
            f"NOT RELIABLE (avg MAPE {avg_mape:.1%}) — do NOT cite specific forecast numbers. "
            "Use forecast only to confirm demand direction (up/flat/down). "
            "Ground all quantity and revenue estimates in analyst KPIs instead."
        )
    else:
        verdict = "UNKNOWN RELIABILITY — treat as directional only."

    lines = [
        f"Demand Signal Assessment",
        f"Model: {report.model_name} | Horizon: {report.horizon_days} days",
        f"Reliability: {verdict}",
        "",
        "Per-SKU backtest (28-day holdout):",
    ]
    for bm in report.backtest_metrics[:5]:
        mape_str = f"{bm.mape:.1%}" if bm.mape is not None else "N/A"
        rmse_str = f"{bm.rmse:.2f}" if bm.rmse is not None else "N/A"
        lines.append(f"  {bm.stock_code}: MAPE={mape_str}, RMSE={rmse_str}")
    return "\n".join(lines)


class ManagerAgent:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.llm = build_llm(self.settings)

    def run(
        self,
        ctx: RunContext,
        analyst_report: AnalystReport,
        forecast_report: ForecastReport,
    ) -> Decision:
        logger.info("manager_agent.start", run_id=ctx.run_id)

        prompt = load_prompt("manager")
        user_msg = (
            prompt["user"].format(
                analyst_report_summary=_summarize_analyst(analyst_report),
                forecast_report_summary=_summarize_forecast(forecast_report),
                mode=ctx.mode,
                as_of_date=ctx.as_of_date,
                run_id=ctx.run_id,
            )
            + "\n\nReturn a JSON object with exactly these keys: "
            "actions, rationale, confidence, risks, kpi_references, forecast_references. "
            "Do NOT include run_id, as_of_date, or mode. "
            "Each action must have: action_type (one of: restock, markdown, reorder, promo, "
            "staffing, audit_returns, other), description (required), urgency, "
            "and optionally stock_code, category, quantity, expected_impact."
        )

        decision = call_with_repair(
            self.llm,
            prompt["system"],
            user_msg,
            DecisionDraft,
            max_retries=self.settings.max_repair_retries,
        )

        # Ensure run metadata is set correctly regardless of LLM output
        return Decision(
            run_id=ctx.run_id,
            as_of_date=ctx.as_of_date,
            mode=ctx.mode,
            actions=decision.actions,
            rationale=decision.rationale,
            confidence=decision.confidence,
            risks=decision.risks,
            kpi_references=decision.kpi_references,
            forecast_references=decision.forecast_references,
        )
