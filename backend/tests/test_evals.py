"""Tests for the three evaluation harnesses and auditor deterministic checks.

All tests use isolated DuckDB files (via tmp_path) — no live warehouse required.
Auditor tests mock build_llm to avoid any network/API calls.
"""

from __future__ import annotations

import json
from datetime import date
from unittest.mock import MagicMock, patch

import duckdb
import pytest

from backend.app.agents.auditor_agent import AuditorAgent
from backend.app.models.decisions import Action, Decision
from backend.app.models.reports import (
    AnalystReport,
    BacktestMetrics,
    ForecastReport,
    ForecastRow,
    KPI,
    QueryEvidence,
)
from backend.app.models.run_context import RunContext
from evals.decision import run_decision_eval
from evals.factuality import run_factuality_eval
from evals.forecasting import run_forecast_eval


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

RUN_ID = "test-run-00000000"
AS_OF = date(2011, 6, 30)
START = date(2011, 4, 1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def db(tmp_path):
    """Isolated DuckDB file with the two tables used by all evals."""
    path = str(tmp_path / "test.duckdb")
    conn = duckdb.connect(path)
    conn.execute(
        """
        CREATE TABLE run_artifacts (
            run_id        VARCHAR,
            artifact_type VARCHAR,
            artifact_json VARCHAR,
            created_at    TIMESTAMP DEFAULT now()
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE fact_sales (
            invoice_no   VARCHAR,
            invoice_date TIMESTAMP,
            stock_code   VARCHAR,
            description  VARCHAR,
            quantity     FLOAT,
            unit_price   FLOAT,
            customer_id  VARCHAR,
            country      VARCHAR,
            revenue      FLOAT
        )
        """
    )
    conn.close()
    return path


def _insert_artifact(db_path: str, artifact_type: str, obj) -> None:
    """Serialize a Pydantic model and insert it into run_artifacts."""
    payload = obj.model_dump_json() if hasattr(obj, "model_dump_json") else json.dumps(obj)
    conn = duckdb.connect(db_path)
    conn.execute(
        "INSERT INTO run_artifacts (run_id, artifact_type, artifact_json) VALUES (?, ?, ?)",
        [RUN_ID, artifact_type, payload],
    )
    conn.close()


def _make_analyst_report(kpis: list[KPI]) -> AnalystReport:
    return AnalystReport(
        run_id=RUN_ID,
        as_of_date=AS_OF,
        mode="bounded",
        period_start=START,
        period_end=AS_OF,
        kpis=kpis,
        narrative="Total revenue was 12345.0 GBP.",
    )


def _make_ctx(mode: str = "bounded") -> RunContext:
    return RunContext(run_id=RUN_ID, start_date=START, as_of_date=AS_OF, mode=mode)


# ---------------------------------------------------------------------------
# Factuality eval tests (4)
# ---------------------------------------------------------------------------


class TestFactualityEval:
    def test_perfect_match_score_is_one(self, db):
        """SQL re-executes to the same value → score 1.0."""
        kpi = KPI(
            name="total_revenue",
            value=12345.0,
            unit="GBP",
            evidence=QueryEvidence(sql="SELECT 12345.0 AS total_revenue"),
        )
        _insert_artifact(db, "analyst_report", _make_analyst_report([kpi]))

        result = run_factuality_eval(RUN_ID, db)

        assert result.factuality_score == 1.0
        assert result.kpis_verified == 1
        assert result.mismatches == []

    def test_mismatch_is_detected(self, db):
        """Stored value differs from re-executed value → mismatch recorded, score 0."""
        kpi = KPI(
            name="total_revenue",
            value=99999.0,  # intentionally wrong
            unit="GBP",
            evidence=QueryEvidence(sql="SELECT 12345.0 AS total_revenue"),
        )
        _insert_artifact(db, "analyst_report", _make_analyst_report([kpi]))

        result = run_factuality_eval(RUN_ID, db)

        assert result.kpis_mismatched == 1
        assert len(result.mismatches) == 1
        assert result.mismatches[0].kpi_name == "total_revenue"
        assert result.factuality_score == 0.0

    def test_kpi_without_evidence_counted_separately(self, db):
        """KPI with no evidence goes to kpis_no_evidence, not kpis_with_evidence."""
        kpi_with = KPI(
            name="revenue",
            value=100.0,
            evidence=QueryEvidence(sql="SELECT 100.0 AS revenue"),
        )
        kpi_without = KPI(name="units_sold", value=500.0, evidence=None)
        _insert_artifact(db, "analyst_report", _make_analyst_report([kpi_with, kpi_without]))

        result = run_factuality_eval(RUN_ID, db)

        assert result.kpis_no_evidence == 1
        assert result.kpis_with_evidence == 1
        assert any("units_sold" in w for w in result.warnings)

    def test_all_kpis_without_evidence_score_is_one(self, db):
        """No evidence to falsify → score defaults to 1.0 (vacuously true)."""
        kpi = KPI(name="units_sold", value=500.0, evidence=None)
        _insert_artifact(db, "analyst_report", _make_analyst_report([kpi]))

        result = run_factuality_eval(RUN_ID, db)

        assert result.factuality_score == 1.0
        assert result.kpis_verified == 0
        assert result.kpis_with_evidence == 0


# ---------------------------------------------------------------------------
# Forecast eval tests (3)
# ---------------------------------------------------------------------------


class TestForecastEval:
    def _make_forecast_report(self, as_of: date = AS_OF, yhat: float = 50.0) -> ForecastReport:
        return ForecastReport(
            run_id=RUN_ID,
            as_of_date=as_of,
            mode="bounded",
            model_name="naive",
            horizon_days=7,
            train_window_days=90,
            forecasts=[
                ForecastRow(stock_code="SKU1", ds="2011-07-01", yhat=yhat),
                ForecastRow(stock_code="SKU1", ds="2011-07-02", yhat=yhat),
            ],
            backtest_metrics=[
                BacktestMetrics(stock_code="SKU1", mape=0.10, rmse=5.0),
            ],
        )

    def test_no_actuals_skus_with_actuals_zero(self, db):
        """When fact_sales has no rows after as_of_date, skus_with_actuals is 0."""
        _insert_artifact(db, "forecast_report", self._make_forecast_report())

        result = run_forecast_eval(RUN_ID, db)

        assert result.skus_with_actuals == 0
        assert result.overall_actual_mape is None
        assert len(result.warnings) >= 1

    def test_actuals_present_mape_near_zero(self, db):
        """When actuals exactly match yhat, MAPE is 0."""
        yhat = 50.0
        _insert_artifact(db, "forecast_report", self._make_forecast_report(yhat=yhat))

        # Insert actuals that exactly match forecasted yhat values
        conn = duckdb.connect(db)
        for inv_no, dt in [("INV001", "2011-07-01"), ("INV002", "2011-07-02")]:
            conn.execute(
                "INSERT INTO fact_sales VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [inv_no, dt, "SKU1", "Test item", yhat, 1.0, "C001", "UK", yhat],
            )
        conn.close()

        result = run_forecast_eval(RUN_ID, db)

        assert result.skus_with_actuals == 1
        sku = result.per_sku[0]
        assert sku.actual_mape is not None
        assert sku.actual_mape < 0.001  # perfect match → MAPE ≈ 0

    def test_missing_artifact_raises_value_error(self, db):
        """Requesting eval with no stored forecast_report raises ValueError."""
        with pytest.raises(ValueError, match="No forecast_report"):
            run_forecast_eval(RUN_ID, db)


# ---------------------------------------------------------------------------
# Decision eval tests (4)
# ---------------------------------------------------------------------------


class TestDecisionEval:
    def _make_decision(
        self,
        confidence: float = 0.75,
        rationale: str = "Revenue dropped 12% this week across top SKUs.",
        kpi_references: list[str] | None = None,
        forecast_references: list[str] | None = None,
        actions: list[Action] | None = None,
    ) -> Decision:
        return Decision(
            run_id=RUN_ID,
            as_of_date=AS_OF,
            mode="bounded",
            confidence=confidence,
            rationale=rationale,
            kpi_references=kpi_references or ["total_revenue"],
            forecast_references=forecast_references or ["SKU1_7d"],
            actions=actions
            or [
                Action(
                    action_type="restock",
                    stock_code="SKU1",
                    description="Restock SKU1 based on forecast demand uplift.",
                    urgency="high",
                )
            ],
        )

    def test_high_quality_decision_score_is_at_least_0_6(self, db):
        """Decision with rationale, KPI refs, forecast refs, targeted action → score >= 0.6."""
        _insert_artifact(db, "decision", self._make_decision())

        result = run_decision_eval(RUN_ID, db)

        assert result.overall_score >= 0.6

    def test_confidence_one_flagged_suspiciously_high(self, db):
        """Confidence == 1.0 should be flagged as suspiciously_high."""
        _insert_artifact(db, "decision", self._make_decision(confidence=1.0))

        result = run_decision_eval(RUN_ID, db)

        assert result.confidence_flag == "suspiciously_high"
        assert any("suspiciously high" in f.lower() for f in result.findings)

    def test_action_without_target_flagged_vague(self, db):
        """Action with no stock_code and no category should be flagged as too vague."""
        vague_action = Action(
            action_type="other",
            description="Do something about the general inventory situation.",
            urgency="low",
        )
        _insert_artifact(db, "decision", self._make_decision(actions=[vague_action]))

        result = run_decision_eval(RUN_ID, db)

        assert result.action_scores[0].has_stock_code_or_category is False
        assert any("too vague" in f.lower() or "no stock_code" in f.lower() for f in result.findings)

    def test_missing_artifact_raises_value_error(self, db):
        """Requesting eval with no stored decision raises ValueError."""
        with pytest.raises(ValueError, match="No decision"):
            run_decision_eval(RUN_ID, db)


# ---------------------------------------------------------------------------
# Auditor deterministic check tests (4)
# ---------------------------------------------------------------------------


class TestAuditorDeterministic:
    """Tests for the three deterministic check methods — no LLM calls needed."""

    @pytest.fixture()
    def auditor(self):
        with patch("backend.app.agents.auditor_agent.build_llm", return_value=MagicMock()):
            return AuditorAgent()

    def test_check_kpi_citations_flags_missing_evidence(self, auditor):
        """KPI with evidence=None should produce a missing_citation finding."""
        ctx = _make_ctx()
        report = _make_analyst_report([KPI(name="revenue", value=100.0, evidence=None)])

        findings = auditor._check_kpi_citations(ctx, report)

        assert len(findings) == 1
        assert findings[0].finding_type == "missing_citation"
        assert "revenue" in findings[0].description

    def test_check_kpi_citations_passes_when_all_have_evidence(self, auditor):
        """KPI with valid QueryEvidence should produce no findings."""
        ctx = _make_ctx()
        report = _make_analyst_report(
            [KPI(name="revenue", value=100.0, evidence=QueryEvidence(sql="SELECT 100 AS revenue"))]
        )

        findings = auditor._check_kpi_citations(ctx, report)

        assert findings == []

    def test_check_bounded_mode_flags_future_period_end(self, auditor):
        """In bounded mode, period_end past as_of_date should raise a policy_violation error."""
        ctx = _make_ctx(mode="bounded")  # as_of = 2011-06-30
        report = AnalystReport(
            run_id=RUN_ID,
            as_of_date=AS_OF,
            mode="bounded",
            period_start=START,
            period_end=date(2011, 12, 1),  # future — violates bounded constraint
            kpis=[],
        )

        findings = auditor._check_bounded_mode(ctx, report)

        assert len(findings) == 1
        assert findings[0].severity == "error"
        assert findings[0].finding_type == "policy_violation"

    def test_check_bounded_mode_passes_in_omniscient(self, auditor):
        """In omniscient mode, any period_end is allowed regardless of as_of_date."""
        ctx = _make_ctx(mode="omniscient")
        report = AnalystReport(
            run_id=RUN_ID,
            as_of_date=AS_OF,
            mode="omniscient",
            period_start=START,
            period_end=date(2011, 12, 9),  # future, but omniscient allows it
            kpis=[],
        )

        findings = auditor._check_bounded_mode(ctx, report)

        assert findings == []
