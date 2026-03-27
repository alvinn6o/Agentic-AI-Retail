#!/usr/bin/env python3
"""Run a full business cycle and print the results."""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.app.core.logging import configure_logging, get_logger
from backend.app.graph.workflow import run_cycle

configure_logging()
logger = get_logger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a full retail ops business cycle")
    parser.add_argument("--as_of", type=str, required=True, help="As-of date (YYYY-MM-DD)")
    parser.add_argument(
        "--start_date",
        type=str,
        default=None,
        help="Start of the analysis window (YYYY-MM-DD). Defaults to 90 days before --as_of.",
    )
    parser.add_argument(
        "--mode",
        choices=["bounded", "omniscient"],
        default="bounded",
        help="Data access mode",
    )
    parser.add_argument(
        "--control_profile",
        choices=["standard", "regulated"],
        default="standard",
        help="Structured-control profile for release gating",
    )
    parser.add_argument(
        "--skip_ingest",
        action="store_true",
        help="Skip data ingestion (assumes data already loaded)",
    )
    args = parser.parse_args()

    as_of = date.fromisoformat(args.as_of)

    if args.start_date is not None:
        start_date = date.fromisoformat(args.start_date)
        if start_date >= as_of:
            print(f"ERROR: --start_date ({start_date}) must be before --as_of ({as_of})", file=sys.stderr)
            sys.exit(1)
    else:
        start_date = None  # run_cycle defaults to as_of - 90 days

    logger.info(
        "run_cycle.start",
        as_of=str(as_of),
        start_date=str(start_date),
        mode=args.mode,
        control_profile=args.control_profile,
    )

    state = run_cycle(
        as_of,
        args.mode,
        start_date=start_date,
        control_profile=args.control_profile,
        skip_ingest=args.skip_ingest,
    )

    print("\n" + "=" * 60)
    print(f"Run ID: {state['ctx'].run_id}")
    print(f"Mode:   {args.mode}")
    print(f"Control:{args.control_profile}")
    print(f"Window: {state['ctx'].start_date} to {as_of}")
    print("=" * 60)

    if state.get("errors"):
        print("\n[ERRORS]")
        for err in state["errors"]:
            print(f"  {err}")

    if state.get("analyst_report"):
        r = state["analyst_report"]
        print(f"\n[ANALYST REPORT] — {r.period_start} to {r.period_end}")
        for kpi in r.kpis:
            print(f"  {kpi.name}: {kpi.value} {kpi.unit}")
        print(f"  Narrative: {r.narrative[:200]}...")

    if state.get("forecast_report"):
        fr = state["forecast_report"]
        print(f"\n[FORECAST REPORT] — model={fr.model_name}, horizon={fr.horizon_days}d")
        for bm in fr.backtest_metrics[:3]:
            mape = f"{bm.mape:.1%}" if bm.mape else "N/A"
            print(f"  {bm.stock_code}: MAPE={mape}")

    if state.get("decision"):
        d = state["decision"]
        print(f"\n[DECISION] — confidence={d.confidence:.0%}")
        for action in d.actions[:5]:
            print(f"  [{action.urgency}] {action.action_type}: {action.description[:80]}")

    if state.get("control_review"):
        cr = state["control_review"]
        print(f"\n[CONTROL REVIEW] — state={cr.overall_state}")
        print(f"  {cr.summary}")

    if state.get("worker_tasks"):
        print(f"\n[WORKER TASKS] — {len(state['worker_tasks'])} tasks generated")
        for task in state["worker_tasks"][:3]:
            print(f"  [{task.priority}] {task.assigned_to}: {task.title}")

    if state.get("audit_report"):
        ar = state["audit_report"]
        status = "PASSED" if ar.passed else "FAILED"
        print(f"\n[AUDIT] {status} — {len(ar.findings)} findings")
        for f in ar.findings[:3]:
            print(f"  [{f.severity}] {f.finding_type}: {f.description[:80]}")

    if state.get("dispatch_report"):
        dr = state["dispatch_report"]
        print(f"\n[DISPATCH] {dr.status.upper()} — {dr.summary}")

    print("\nDone.")


if __name__ == "__main__":
    main()
