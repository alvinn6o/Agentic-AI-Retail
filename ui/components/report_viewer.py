"""Streamlit components for displaying analyst and forecast reports."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from ui.components.charts import forecast_chart, kpi_cards


def show_analyst_report(report: dict[str, Any]) -> None:
    st.subheader("Analyst Report")
    col1, col2 = st.columns(2)
    with col1:
        st.write(f"**Period:** {report.get('period_start')} → {report.get('period_end')}")
    with col2:
        st.write(f"**Mode:** {report.get('mode', '').upper()}")

    # KPI Cards
    kpis = report.get("kpis", [])
    if kpis:
        st.markdown("#### Key Performance Indicators")
        cols = st.columns(min(len(kpis), 5))
        for i, kpi_data in enumerate(kpi_cards(kpis)):
            with cols[i % len(cols)]:
                value = kpi_data["value"]
                unit = kpi_data["unit"]
                display = f"£{value:,.2f}" if unit == "GBP" else f"{value:,.1f} {unit}"
                st.metric(kpi_data["label"], display)

    # Top SKUs table (top 10 by revenue)
    top_skus = report.get("top_skus", [])
    if top_skus:
        st.markdown("#### Top 10 SKUs by Revenue")
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
        st.dataframe(skus_df[display_cols], use_container_width=True, hide_index=True)

    # Narrative
    narrative = report.get("narrative", "")
    if narrative:
        st.markdown("#### Narrative")
        st.info(narrative)

    # Anomalies
    anomalies = report.get("anomalies", [])
    if anomalies:
        st.markdown("#### Anomalies")
        for a in anomalies:
            severity = a.get("severity", "info")
            icon = {"high": "[HIGH]", "medium": "[MED]", "low": "[LOW]"}.get(severity, "[INFO]")
            st.write(f"{icon} **{severity.upper()}**: {a.get('description')}")

    # Evidence
    queries = report.get("queries_executed", [])
    if queries:
        with st.expander(f"SQL Evidence ({len(queries)} queries)"):
            for q in queries:
                st.code(q.get("sql", ""), language="sql")


def show_forecast_report(report: dict[str, Any]) -> None:
    st.subheader("Demand Signal Assessment")

    # Reliability verdict based on average MAPE
    backtest = report.get("backtest_metrics", [])
    valid_mapes = [m["mape"] for m in backtest if m.get("mape") is not None]
    avg_mape = sum(valid_mapes) / len(valid_mapes) if valid_mapes else None
    if avg_mape is None:
        st.warning("Forecast reliability unknown — no backtest metrics available.")
    elif avg_mape > 1.0:
        st.error(
            f"**Model NOT reliable** — average MAPE {avg_mape:.1%}. "
            "Forecast direction may be used for planning but specific values should not be cited."
        )
    else:
        st.success(f"**Model reliable** — average MAPE {avg_mape:.1%}.")

    st.caption(
        f"Model: {report.get('model_name')} | Horizon: {report.get('horizon_days')} days"
    )

    backtest = report.get("backtest_metrics", [])
    if backtest:
        st.markdown("#### Backtest Metrics")
        bdf = pd.DataFrame(backtest)
        if "mape" in bdf.columns:
            bdf["mape"] = bdf["mape"].apply(lambda x: f"{x:.1%}" if x is not None else "N/A")
        if "rmse" in bdf.columns:
            bdf["rmse"] = bdf["rmse"].apply(lambda x: f"{x:.2f}" if x is not None else "N/A")
        st.dataframe(bdf, use_container_width=True)

    forecasts = report.get("forecasts", [])
    if forecasts:
        skus = sorted({f["stock_code"] for f in forecasts})
        selected = st.selectbox("Select SKU for forecast chart", skus)
        if selected:
            st.plotly_chart(forecast_chart(forecasts, selected), use_container_width=True)

            # Forecast data table for selected SKU
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
            st.dataframe(fdf, use_container_width=True, hide_index=True)

    assumptions = report.get("assumptions", [])
    if assumptions:
        with st.expander("Assumptions"):
            for a in assumptions:
                st.write(f"• {a}")
