"""AnalystAgent — produces KPI reports grounded in SQL queries."""

from __future__ import annotations

from datetime import date

from backend.app.agents.base import build_llm, call_with_repair, load_prompt
from backend.app.core.config import Settings, get_settings
from backend.app.core.logging import get_logger
from backend.app.models.reports import AnalystNarrative, AnalystReport, KPI, QueryEvidence
from backend.app.models.run_context import RunContext
from backend.app.tools.sql_tool import SQLTool

logger = get_logger(__name__)


class AnalystAgent:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.llm = build_llm(self.settings)

    def run(self, ctx: RunContext, period_start: date, period_end: date) -> AnalystReport:
        logger.info("analyst_agent.start", run_id=ctx.run_id, mode=ctx.mode)

        sql = SQLTool(ctx.as_of_date, ctx.mode, self.settings)
        queries_executed: list[QueryEvidence] = []

        # --- Pre-compute key metrics with SQL (grounded) ---
        revenue_rows, rev_ev = sql.run(
            """
            SELECT
                SUM(revenue)                                        AS total_revenue,
                COUNT(DISTINCT invoice_no)                          AS total_orders,
                SUM(revenue) / COUNT(DISTINCT invoice_no)           AS avg_order_value,
                COUNT(DISTINCT customer_id)                         AS unique_customers
            FROM fact_sales
            WHERE invoice_date BETWEEN ? AND ?
            """,
            [str(period_start), str(period_end)],
            step="total_kpis",
        )
        queries_executed.append(rev_ev)

        top_sku_rows, top_ev = sql.run(
            """
            SELECT
                stock_code,
                (
                    SELECT description
                    FROM fact_sales f2
                    WHERE f2.stock_code = f.stock_code
                      AND TRIM(f2.description) <> ''
                    GROUP BY description
                    ORDER BY COUNT(*) DESC
                    LIMIT 1
                ) AS description,
                SUM(revenue)   AS total_revenue,
                SUM(quantity)  AS total_units
            FROM fact_sales f
            WHERE invoice_date BETWEEN ? AND ?
            GROUP BY stock_code
            ORDER BY total_revenue DESC
            LIMIT 10
            """,
            [str(period_start), str(period_end)],
            step="top_skus",
        )
        queries_executed.append(top_ev)

        bottom_sku_rows, bot_ev = sql.run(
            """
            SELECT
                stock_code,
                (
                    SELECT description
                    FROM fact_sales f2
                    WHERE f2.stock_code = f.stock_code
                      AND TRIM(f2.description) <> ''
                    GROUP BY description
                    ORDER BY COUNT(*) DESC
                    LIMIT 1
                ) AS description,
                SUM(revenue)   AS total_revenue,
                SUM(quantity)  AS total_units
            FROM fact_sales f
            WHERE invoice_date BETWEEN ? AND ?
            GROUP BY stock_code
            HAVING SUM(quantity) >= 5
            ORDER BY total_revenue ASC
            LIMIT 10
            """,
            [str(period_start), str(period_end)],
            step="bottom_skus",
        )
        queries_executed.append(bot_ev)

        return_rows, ret_ev = sql.run(
            """
            SELECT
                COUNT(*) AS return_count,
                (SELECT COUNT(*) FROM fact_sales
                 WHERE invoice_date BETWEEN ? AND ?) AS total_count
            FROM fact_sales
            WHERE quantity < 0
              AND invoice_date BETWEEN ? AND ?
            """,
            [str(period_start), str(period_end),
             str(period_start), str(period_end)],
            step="return_rate",
        )
        queries_executed.append(ret_ev)

        # Build KPIs from grounded data
        kpis: list[KPI] = []
        if revenue_rows:
            r = revenue_rows[0]
            kpis = [
                KPI(name="total_revenue", value=float(r.get("total_revenue") or 0),
                    unit="GBP", period=f"{period_start}/{period_end}", evidence=rev_ev),
                KPI(name="total_orders", value=float(r.get("total_orders") or 0),
                    unit="orders", period=f"{period_start}/{period_end}", evidence=rev_ev),
                KPI(name="avg_order_value", value=float(r.get("avg_order_value") or 0),
                    unit="GBP", period=f"{period_start}/{period_end}", evidence=rev_ev),
                KPI(name="unique_customers", value=float(r.get("unique_customers") or 0),
                    unit="customers", period=f"{period_start}/{period_end}", evidence=rev_ev),
            ]
        if return_rows:
            rr = return_rows[0]
            total = rr.get("total_count") or 1
            rate = (rr.get("return_count") or 0) / total
            kpis.append(KPI(name="return_rate", value=round(rate, 4),
                           unit="ratio", period=f"{period_start}/{period_end}", evidence=ret_ev))

        # Send pre-computed metrics to the model for narrative generation and anomaly detection only.
        # The model receives already-computed numbers and must return ONLY anomalies + narrative.
        prompt = load_prompt("analyst")
        kpi_summary = "\n".join(f"- {k.name}: {k.value} {k.unit}" for k in kpis)
        top_summary = "\n".join(
            f"  {r.get('stock_code')} {r.get('description', '')}: £{r.get('total_revenue', 0):.2f}"
            for r in top_sku_rows[:10]
        )
        bottom_summary = "\n".join(
            f"  {r.get('stock_code')} {r.get('description', '')}: £{r.get('total_revenue', 0):.2f}"
            for r in bottom_sku_rows[:10]
        )

        user_msg = (
            f"Period: {period_start} to {period_end} | Mode: {ctx.mode} | As-of: {ctx.as_of_date}\n\n"
            f"PRE-COMPUTED KPIs (do not change these values):\n{kpi_summary}\n\n"
            f"Top 10 SKUs by revenue:\n{top_summary}\n\n"
            f"Bottom 10 SKUs by revenue:\n{bottom_summary}\n\n"
            "Return a JSON object with exactly two keys:\n"
            '  "anomalies": list of {description, severity, affected_skus} objects\n'
            '  "narrative": a 3-5 sentence plain-text summary\n\n'
            "Do not include KPIs, SKU lists, or query evidence — those are already computed."
        )

        report_partial = call_with_repair(
            self.llm,
            prompt["system"],
            user_msg,
            AnalystNarrative,
            max_retries=self.settings.max_repair_retries,
        )

        # Reconstruct the report using the SQL-computed KPIs.
        # Model-generated narrative and anomalies are accepted, but computed numbers are never replaced.
        final = AnalystReport(
            run_id=ctx.run_id,
            as_of_date=ctx.as_of_date,
            mode=ctx.mode,
            period_start=period_start,
            period_end=period_end,
            kpis=kpis,                           # always use computed kpis
            top_skus=top_sku_rows,
            bottom_skus=bottom_sku_rows,
            anomalies=report_partial.anomalies,
            narrative=report_partial.narrative,
            queries_executed=queries_executed,
        )

        logger.info("analyst_agent.done", run_id=ctx.run_id, num_kpis=len(kpis))
        return final
