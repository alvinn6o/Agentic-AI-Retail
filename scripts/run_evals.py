#!/usr/bin/env python3
"""Run evaluation harnesses for a completed workflow run.

Usage:
    python scripts/run_evals.py --run_id <uuid>
    python scripts/run_evals.py --run_id <uuid> --eval factuality
    python scripts/run_evals.py --run_id <uuid> --eval forecasting
    python scripts/run_evals.py --run_id <uuid> --eval decision
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.app.core.config import get_settings
from backend.app.core.logging import configure_logging, get_logger
from evals.decision import run_decision_eval
from evals.factuality import run_factuality_eval
from evals.forecasting import run_forecast_eval

configure_logging()
logger = get_logger(__name__)


def _section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print("=" * 60)


def _run_factuality(run_id: str, db_path: str) -> None:
    _section("FACTUALITY EVAL")
    try:
        result = run_factuality_eval(run_id, db_path)
        status = "PASS" if result.factuality_score >= 0.8 else "FAIL"
        print(f"  Status  : {status}")
        print(f"  Score   : {result.factuality_score:.3f}")
        print(
            f"  KPIs    : {result.total_kpis} total | "
            f"{result.kpis_with_evidence} with evidence | "
            f"{result.kpis_verified} verified | "
            f"{result.kpis_mismatched} mismatched"
        )
        if result.mismatches:
            print("  Mismatches:")
            for m in result.mismatches:
                print(
                    f"    [{m.kpi_name}] "
                    f"stored={m.stored_value:.4f}  "
                    f"recomputed={m.recomputed_value:.4f}  "
                    f"rel_err={m.relative_error:.2%}"
                )
        if result.narrative_numbers_not_in_kpis:
            print(f"  Narrative numbers not traceable to KPIs: {result.narrative_numbers_not_in_kpis}")
        if result.warnings:
            print("  Warnings:")
            for w in result.warnings:
                print(f"    {w}")
    except ValueError as exc:
        print(f"  [SKIP] {exc}")


def _run_forecasting(run_id: str, db_path: str) -> None:
    _section("FORECAST EVAL")
    try:
        result = run_forecast_eval(run_id, db_path)
        has_actuals = result.skus_with_actuals > 0
        status = "PASS" if has_actuals else "N/A (no actuals yet)"
        print(f"  Status         : {status}")
        print(f"  Model          : {result.model_name}")
        print(f"  As-of date     : {result.as_of_date}")
        print(f"  SKUs forecasted: {result.total_skus_forecasted}")
        print(f"  SKUs w/actuals : {result.skus_with_actuals}")
        if result.overall_actual_mape is not None:
            print(f"  Overall MAPE   : {result.overall_actual_mape:.2%}")
        if result.overall_actual_rmse is not None:
            print(f"  Overall RMSE   : {result.overall_actual_rmse:.2f}")
        unreliable = [s for s in result.per_sku if s.backtest_is_reliable is False]
        if unreliable:
            print(f"  Over-optimistic backtest SKUs ({len(unreliable)}):")
            for s in unreliable[:5]:
                print(
                    f"    {s.stock_code}: "
                    f"backtest_mape={s.backtest_mape:.2%}  "
                    f"actual_mape={s.actual_mape:.2%}"
                )
        if result.warnings:
            print(f"  Warnings ({len(result.warnings)} total, first 5):")
            for w in result.warnings[:5]:
                print(f"    {w}")
    except ValueError as exc:
        print(f"  [SKIP] {exc}")


def _run_decision(run_id: str, db_path: str) -> None:
    _section("DECISION EVAL")
    try:
        result = run_decision_eval(run_id, db_path)
        status = "PASS" if result.overall_score >= 0.6 else "FAIL"
        print(f"  Status      : {status}")
        print(f"  Score       : {result.overall_score:.3f}")
        print(f"  Actions     : {result.total_actions}")
        print(f"  Rationale   : {'yes' if result.has_rationale else 'NO'}")
        print(f"  KPI refs    : {'yes' if result.has_kpi_references else 'NO'}")
        print(f"  Fcst refs   : {'yes' if result.has_forecast_references else 'NO'}")
        print(f"  Confidence  : {result.confidence:.2f} [{result.confidence_flag}]")
        if result.findings:
            print(f"  Findings ({len(result.findings)}):")
            for f in result.findings:
                print(f"    {f}")
        if result.action_scores:
            print("  Per-action scores:")
            for s in result.action_scores:
                print(f"    [{s.action_type}] score={s.score:.2f}  target={'yes' if s.has_stock_code_or_category else 'NO'}  kpi_ref={'yes' if s.rationale_references_kpi else 'NO'}")
    except ValueError as exc:
        print(f"  [SKIP] {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run evaluation harnesses for a completed workflow run"
    )
    parser.add_argument("--run_id", required=True, help="Run UUID printed by run_cycle.py")
    parser.add_argument(
        "--eval",
        choices=["all", "factuality", "forecasting", "decision"],
        default="all",
        help="Which eval to run (default: all)",
    )
    args = parser.parse_args()

    settings = get_settings()
    db_path = str(settings.duckdb_path)

    print(f"\nRun ID   : {args.run_id}")
    print(f"Warehouse: {db_path}")

    if args.eval in ("all", "factuality"):
        _run_factuality(args.run_id, db_path)
    if args.eval in ("all", "forecasting"):
        _run_forecasting(args.run_id, db_path)
    if args.eval in ("all", "decision"):
        _run_decision(args.run_id, db_path)

    print("\nDone.")


if __name__ == "__main__":
    main()
