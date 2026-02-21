"""Typed schemas for analyst and forecast reports."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Evidence — every numeric claim must link back to a tool call
# ---------------------------------------------------------------------------

class QueryEvidence(BaseModel):
    sql: str
    params: list[Any] = Field(default_factory=list)
    result_preview: list[dict[str, Any]] = Field(default_factory=list)
    run_at: str = ""


# ---------------------------------------------------------------------------
# Analyst Report
# ---------------------------------------------------------------------------

class KPI(BaseModel):
    name: str
    value: float
    unit: str = ""
    period: str = ""
    evidence: QueryEvidence | None = None


class Anomaly(BaseModel):
    description: str
    severity: str  # low | medium | high
    affected_skus: list[str] = Field(default_factory=list)
    evidence: QueryEvidence | None = None


class AnalystNarrative(BaseModel):
    """Slim schema used only for the LLM call — avoids regenerating SQL-computed data."""
    anomalies: list[Anomaly] = Field(default_factory=list)
    narrative: str = ""


class AnalystReport(BaseModel):
    run_id: str
    as_of_date: date
    mode: str
    period_start: date
    period_end: date
    kpis: list[KPI] = Field(default_factory=list)
    top_skus: list[dict[str, Any]] = Field(default_factory=list)
    bottom_skus: list[dict[str, Any]] = Field(default_factory=list)
    anomalies: list[Anomaly] = Field(default_factory=list)
    narrative: str = ""
    queries_executed: list[QueryEvidence] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Forecast Report
# ---------------------------------------------------------------------------

class ForecastRow(BaseModel):
    stock_code: str
    ds: str           # date string YYYY-MM-DD
    yhat: float
    yhat_lower: float | None = None
    yhat_upper: float | None = None


class BacktestMetrics(BaseModel):
    stock_code: str
    mape: float | None = None
    rmse: float | None = None
    mae: float | None = None
    train_start: str = ""
    train_end: str = ""
    horizon_days: int = 0


class ForecastReport(BaseModel):
    run_id: str
    as_of_date: date
    mode: str
    model_name: str                        # e.g. "prophet", "lightgbm", "naive"
    horizon_days: int
    train_window_days: int
    forecasts: list[ForecastRow] = Field(default_factory=list)
    backtest_metrics: list[BacktestMetrics] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    queries_executed: list[QueryEvidence] = Field(default_factory=list)
