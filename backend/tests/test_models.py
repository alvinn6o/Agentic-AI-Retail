"""Tests for Pydantic model validation."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from backend.app.models.decisions import Action, Decision, WorkerTask
from backend.app.models.reports import AnalystReport, ForecastReport, KPI
from backend.app.models.run_context import RunContext


class TestRunContext:
    def test_creates_run_id(self) -> None:
        ctx = RunContext(start_date=date(2011, 4, 1), as_of_date=date(2011, 6, 30), mode="bounded")
        assert len(ctx.run_id) == 36  # UUID

    def test_mode_validation(self) -> None:
        with pytest.raises(ValidationError):
            RunContext(start_date=date(2011, 4, 1), as_of_date=date(2011, 6, 30), mode="invalid")  # type: ignore


class TestDecision:
    def test_confidence_bounds(self) -> None:
        with pytest.raises(ValidationError):
            Decision(
                run_id="test",
                as_of_date=date(2011, 6, 30),
                mode="bounded",
                rationale="test",
                confidence=1.5,  # out of range
            )

    def test_valid_decision(self) -> None:
        d = Decision(
            run_id="test",
            as_of_date=date(2011, 6, 30),
            mode="bounded",
            rationale="Based on analysis",
            confidence=0.8,
            actions=[
                Action(
                    action_type="restock",
                    stock_code="85123A",
                    description="Restock top seller",
                    quantity=100,
                )
            ],
        )
        assert d.confidence == 0.8
        assert len(d.actions) == 1


class TestAnalystReport:
    def test_serialization(self) -> None:
        ctx = RunContext(start_date=date(2011, 4, 1), as_of_date=date(2011, 6, 30), mode="bounded")
        report = AnalystReport(
            run_id=ctx.run_id,
            as_of_date=date(2011, 6, 30),
            mode="bounded",
            period_start=date(2011, 4, 1),
            period_end=date(2011, 6, 30),
            kpis=[KPI(name="total_revenue", value=50000.0, unit="GBP")],
        )
        data = report.model_dump()
        assert data["kpis"][0]["name"] == "total_revenue"
        assert data["kpis"][0]["value"] == 50000.0
