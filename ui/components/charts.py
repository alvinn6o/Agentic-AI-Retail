"""Plotly chart helpers for the Streamlit UI."""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.graph_objects as go


def _apply_enterprise_layout(fig: go.Figure, title: str) -> go.Figure:
    fig.update_layout(
        title=title,
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(255,255,255,0)",
        font={"family": "IBM Plex Sans, sans-serif", "color": "#132534"},
        margin={"l": 12, "r": 12, "t": 64, "b": 24},
        title_font={"size": 19, "color": "#132534"},
        hoverlabel={"bgcolor": "#132534", "font_color": "#f6f9fb"},
    )
    fig.update_xaxes(
        showline=False,
        zeroline=False,
        gridcolor="rgba(19, 37, 52, 0.08)",
        tickfont={"color": "#5e7183"},
        title_font={"color": "#5e7183"},
    )
    fig.update_yaxes(
        showline=False,
        zeroline=False,
        gridcolor="rgba(19, 37, 52, 0.08)",
        tickfont={"color": "#5e7183"},
        title_font={"color": "#5e7183"},
    )
    return fig


def top_skus_bar(skus: list[dict[str, Any]], title: str = "Top SKUs by Revenue") -> go.Figure:
    df = pd.DataFrame(skus)
    if df.empty or "total_revenue" not in df.columns:
        return go.Figure()
    df = df.sort_values("total_revenue", ascending=True).tail(10)
    fig = go.Figure(
        go.Bar(
            x=df["total_revenue"],
            y=df["stock_code"],
            orientation="h",
            marker={
                "color": "#0d6b73",
                "line": {"color": "#0a4d56", "width": 1},
            },
            text=[f"GBP {value:,.0f}" for value in df["total_revenue"]],
            textposition="outside",
            hovertemplate="SKU %{y}<br>Revenue GBP %{x:,.2f}<extra></extra>",
        )
    )
    fig.update_layout(showlegend=False, xaxis_title="Revenue (GBP)", yaxis_title="SKU")
    return _apply_enterprise_layout(fig, title)


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
        name="Forecast", line={"color": "#0d6b73", "width": 3},
        mode="lines+markers",
        marker={"size": 6, "color": "#0a4d56"},
        hovertemplate="%{x}<br>Predicted units %{y:.1f}<extra></extra>",
    ))
    if "yhat_upper" in df.columns and "yhat_lower" in df.columns:
        fig.add_trace(go.Scatter(
            x=pd.concat([df["ds"], df["ds"][::-1]]),
            y=pd.concat([df["yhat_upper"], df["yhat_lower"][::-1]]),
            fill="toself",
            fillcolor="rgba(13, 107, 115, 0.14)",
            line={"color": "rgba(255,255,255,0)"},
            name="Uncertainty",
            hoverinfo="skip",
        ))
    fig.update_layout(
        xaxis_title="Date",
        yaxis_title="Units",
        legend={"orientation": "h", "x": 0, "y": 1.1},
    )
    return _apply_enterprise_layout(fig, f"Demand Forecast - {stock_code}")
