"""Plotly chart helpers for the Streamlit UI."""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


def top_skus_bar(skus: list[dict[str, Any]], title: str = "Top SKUs by Revenue") -> go.Figure:
    df = pd.DataFrame(skus)
    if df.empty or "total_revenue" not in df.columns:
        return go.Figure()
    df = df.sort_values("total_revenue", ascending=True).tail(10)
    fig = px.bar(
        df,
        x="total_revenue",
        y="stock_code",
        orientation="h",
        title=title,
        labels={"total_revenue": "Revenue (£)", "stock_code": "SKU"},
        color="total_revenue",
        color_continuous_scale="Blues",
    )
    fig.update_layout(showlegend=False, coloraxis_showscale=False)
    return fig


def kpi_cards(kpis: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return formatted KPI data for rendering as st.metric cards."""
    return [
        {
            "label": k.get("name", "").replace("_", " ").title(),
            "value": k.get("value", 0),
            "unit": k.get("unit", ""),
        }
        for k in kpis
    ]


def forecast_chart(forecasts: list[dict[str, Any]], stock_code: str) -> go.Figure:
    df = pd.DataFrame([f for f in forecasts if f.get("stock_code") == stock_code])
    if df.empty:
        return go.Figure()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["ds"], y=df["yhat"],
        name="Forecast", line=dict(color="royalblue", width=2),
    ))
    if "yhat_upper" in df.columns and "yhat_lower" in df.columns:
        fig.add_trace(go.Scatter(
            x=pd.concat([df["ds"], df["ds"][::-1]]),
            y=pd.concat([df["yhat_upper"], df["yhat_lower"][::-1]]),
            fill="toself",
            fillcolor="rgba(65,105,225,0.15)",
            line=dict(color="rgba(255,255,255,0)"),
            name="Uncertainty",
        ))
    fig.update_layout(
        title=f"Demand Forecast — {stock_code}",
        xaxis_title="Date",
        yaxis_title="Units",
    )
    return fig
