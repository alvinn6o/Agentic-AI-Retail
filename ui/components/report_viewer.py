"""Streamlit components for displaying analyst and forecast reports."""

from __future__ import annotations

from html import escape
from typing import Any

import pandas as pd
import streamlit as st

from ui.components.charts import forecast_chart, kpi_cards, top_skus_bar
from ui.components.enterprise_ui import (
    render_detail_card,
    render_section_heading,
    render_summary_card,
    status_pill_html,
)


def _format_metric_value(value: Any, unit: str) -> str:
    if unit == "GBP":
        return f"GBP {float(value):,.2f}"
    if value is None:
        return "-"
    if unit:
        return f"{float(value):,.1f} {unit}"
    return f"{float(value):,.1f}"


def show_analyst_report(report: dict[str, Any]) -> None:
    render_section_heading(
        "Analyst Report",
        "Grounded KPI view with evidence-backed narrative, top sellers, and anomaly review.",
        eyebrow="Performance Intelligence",
    )

    period = f"{report.get('period_start')} to {report.get('period_end')}"
    queries = report.get("queries_executed", [])
    col1, col2, col3 = st.columns(3)
    with col1:
        render_summary_card("Analysis Window", period, "Selected bounded or omniscient interval.")
    with col2:
        render_summary_card("Mode", report.get("mode", "").upper() or "-", "Data visibility profile.")
    with col3:
        render_summary_card("Evidence Queries", str(len(queries)), "Deterministic SQL statements captured.")

    kpis = report.get("kpis", [])
    if kpis:
        render_section_heading(
            "Key Performance Indicators",
            "Operational KPIs grounded in SQL before any narrative generation.",
            eyebrow="Metrics",
        )
        cols = st.columns(min(len(kpis), 5))
        for i, kpi_data in enumerate(kpi_cards(kpis)):
            with cols[i % len(cols)]:
                render_summary_card(
                    kpi_data["label"],
                    _format_metric_value(kpi_data["value"], kpi_data["unit"]),
                    "Evidence-backed KPI",
                )

    top_skus = report.get("top_skus", [])
    if top_skus:
        render_section_heading(
            "Revenue Concentration",
            "Top performers by revenue, shown as both a visual ranking and a tabular view.",
            eyebrow="Merchandise Mix",
        )
        skus_sorted = sorted(top_skus, key=lambda x: float(x.get("total_revenue") or 0), reverse=True)[:10]
        skus_df = pd.DataFrame(skus_sorted)
        col_map = {
            "stock_code": "Stock Code",
            "description": "Description",
            "total_revenue": "Revenue (GBP)",
            "total_units": "Units Sold",
        }
        skus_df = skus_df.rename(columns={k: v for k, v in col_map.items() if k in skus_df.columns})
        if "Revenue (GBP)" in skus_df.columns:
            skus_df["Revenue (GBP)"] = skus_df["Revenue (GBP)"].apply(
                lambda x: f"£{float(x):,.2f}" if x is not None else "—"
            )
        if "Units Sold" in skus_df.columns:
            skus_df["Units Sold"] = skus_df["Units Sold"].apply(
                lambda x: f"{int(float(x)):,}" if x is not None else "—"
            )
        display_cols = [c for c in ["Stock Code", "Description", "Revenue (GBP)", "Units Sold"] if c in skus_df.columns]
        chart_col, table_col = st.columns([1.1, 1])
        with chart_col:
            st.plotly_chart(
                top_skus_bar(skus_sorted, title="Top 10 SKUs by Revenue"),
                use_container_width=True,
                config={"displayModeBar": False},
            )
        with table_col:
            st.dataframe(skus_df[display_cols], use_container_width=True, hide_index=True)

    narrative = report.get("narrative", "")
    if narrative:
        render_section_heading(
            "Narrative Synthesis",
            "Short analyst interpretation constrained by precomputed evidence.",
            eyebrow="Summary",
        )
        render_detail_card("Analyst Narrative", escape(narrative).replace("\n", "<br>"))

    anomalies = report.get("anomalies", [])
    if anomalies:
        render_section_heading(
            "Anomalies",
            "Potential issues highlighted from the KPI and sales patterns.",
            eyebrow="Exceptions",
        )
        for a in anomalies:
            severity = a.get("severity", "info")
            tone = {"high": "danger", "medium": "warning", "low": "info"}.get(severity, "neutral")
            render_detail_card(
                a.get("description", "Detected anomaly"),
                "Investigation recommended before execution.",
                pills=[status_pill_html(severity.upper(), tone)],
            )

    if queries:
        render_section_heading(
            "SQL Evidence",
            "The exact queries used to ground the KPI and narrative outputs.",
            eyebrow="Traceability",
        )
        with st.expander(f"Inspect SQL evidence ({len(queries)} queries)"):
            for q in queries:
                st.code(q.get("sql", ""), language="sql")


def show_forecast_report(report: dict[str, Any]) -> None:
    render_section_heading(
        "Demand Signal Assessment",
        "Forecast reliability, SKU-level backtests, and the operational demand outlook.",
        eyebrow="Forecasting",
    )

    backtest = report.get("backtest_metrics", [])
    valid_mapes = [m["mape"] for m in backtest if m.get("mape") is not None]
    avg_mape = sum(valid_mapes) / len(valid_mapes) if valid_mapes else None
    reliability_label = "Unknown"
    reliability_detail = "No backtest metrics available."
    reliability_tone = "neutral"
    if avg_mape is None:
        reliability_tone = "warning"
    elif avg_mape > 1.0:
        reliability_label = f"Directional Only ({avg_mape:.1%} MAPE)"
        reliability_detail = "Use the forecast for directional planning, not exact quantities."
        reliability_tone = "danger"
    else:
        reliability_label = f"Reliable ({avg_mape:.1%} MAPE)"
        reliability_detail = "Specific forecast values are appropriate for planning."
        reliability_tone = "success"

    col1, col2, col3 = st.columns(3)
    with col1:
        render_summary_card("Reliability", reliability_label, reliability_detail)
    with col2:
        render_summary_card("Model", str(report.get("model_name", "-")), "Forecasting engine.")
    with col3:
        render_summary_card(
            "Horizon",
            f"{report.get('horizon_days', 0)} days",
            f"{len(backtest)} SKU backtests captured.",
        )

    render_detail_card(
        "Reliability Guidance",
        "Forecast reliability is assessed from held-out backtests before downstream decisioning.",
        pills=[status_pill_html(reliability_label, reliability_tone)],
    )

    if backtest:
        render_section_heading(
            "Backtest Metrics",
            "Per-SKU holdout metrics used to judge forecast quality before decisions are made.",
            eyebrow="Validation",
        )
        bdf = pd.DataFrame(backtest)
        if "mape" in bdf.columns:
            bdf["mape"] = bdf["mape"].apply(lambda x: f"{x:.1%}" if x is not None else "N/A")
        if "rmse" in bdf.columns:
            bdf["rmse"] = bdf["rmse"].apply(lambda x: f"{x:.2f}" if x is not None else "N/A")
        st.dataframe(bdf, use_container_width=True, hide_index=True)

    forecasts = report.get("forecasts", [])
    if forecasts:
        render_section_heading(
            "Forecast Explorer",
            "Inspect the released forecast band for a specific SKU.",
            eyebrow="Scenario View",
        )
        skus = sorted({f["stock_code"] for f in forecasts})
        selected = st.selectbox("Select SKU for forecast chart", skus)
        if selected:
            chart_col, table_col = st.columns([1.15, 0.85])
            with chart_col:
                st.plotly_chart(
                    forecast_chart(forecasts, selected),
                    use_container_width=True,
                    config={"displayModeBar": False},
                )

            sku_rows = [f for f in forecasts if f.get("stock_code") == selected]
            fdf = pd.DataFrame(sku_rows)[["ds", "yhat", "yhat_lower", "yhat_upper"]].copy()
            fdf = fdf.rename(columns={
                "ds": "Date",
                "yhat": "Predicted Qty",
                "yhat_lower": "Lower Bound",
                "yhat_upper": "Upper Bound",
            })
            for col in ["Predicted Qty", "Lower Bound", "Upper Bound"]:
                fdf[col] = fdf[col].apply(lambda x: round(float(x), 1) if x is not None else None)
            with table_col:
                st.dataframe(fdf, use_container_width=True, hide_index=True)

    assumptions = report.get("assumptions", [])
    if assumptions:
        render_section_heading(
            "Forecast Assumptions",
            "Model caveats and contextual assumptions that should accompany the forecast.",
            eyebrow="Model Notes",
        )
        with st.expander("Inspect assumptions"):
            for a in assumptions:
                st.write(f"• {a}")
