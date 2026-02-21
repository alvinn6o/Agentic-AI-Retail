"""Agentic Retail Ops Simulator — Streamlit UI."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import json
from datetime import date, timedelta

import httpx
import streamlit as st

from ui.components.decision_panel import show_audit_report, show_decision, show_worker_tasks
from ui.components.report_viewer import show_analyst_report, show_forecast_report
from ui.utils.pdf_export import generate_report_pdf

API_BASE = "http://localhost:8000/api/v1"

st.set_page_config(
    page_title="Retail Ops Simulator",
    layout="wide",
)

# ─── Sidebar ─────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("Retail Ops Simulator")
    st.markdown("---")

    st.markdown("### Run Settings")
    st.caption("Dataset range: 1 Dec 2010 to 9 Dec 2011")

    DATA_MIN = date(2010, 12, 1)
    DATA_MAX = date(2011, 12, 9)

    start_date = st.date_input(
        "Start Date",
        value=date(2011, 4, 1),
        min_value=DATA_MIN,
        max_value=DATA_MAX,
        help="Beginning of the analysis window.",
    )
    as_of_date = st.date_input(
        "End Date (as-of)",
        value=date(2011, 6, 30),
        min_value=DATA_MIN,
        max_value=DATA_MAX,
        help="End of the analysis window. In bounded mode, agents cannot see data beyond this date.",
    )

    if start_date >= as_of_date:
        st.error("Start date must be before end date.")

    mode_label = st.radio(
        "Data Access Mode",
        ["Custom Range", "Full Range"],
        index=0,
        help="Custom Range: agents see only data within the selected window. Full Range: full dataset available.",
    )
    mode = "bounded" if mode_label == "Custom Range" else "omniscient"

    skip_ingest = st.checkbox(
        "Skip data ingest",
        value=True,
        help="Skip if data is already loaded into DuckDB.",
    )

    st.markdown("---")
    run_btn = st.button("Run Business Cycle", type="primary", use_container_width=True)

    st.markdown("---")
    st.markdown("### Run History")

    try:
        history_resp = httpx.get(f"{API_BASE}/runs", timeout=5)
        past_runs = history_resp.json() if history_resp.is_success else []
    except Exception:
        past_runs = []

    if past_runs:
        run_options = {}
        total = len(past_runs)
        for i, r in enumerate(past_runs):
            # past_runs is DESC (newest first); #1 = first/oldest run
            run_num = total - i
            start = r.get("period_start") or r.get("as_of_date", "?")
            end = r.get("period_end") or r.get("as_of_date", "?")
            label = f"Run #{run_num}: {start} → {end} ({r['mode']})"
            run_options[label] = r["run_id"]
        selected_label = st.selectbox(
            "Select a past run",
            options=list(run_options.keys()),
            index=None,
            placeholder="Choose a run…",
        )
        selected_run_id = run_options.get(selected_label) if selected_label else None
    else:
        st.caption("No past runs found.")
        selected_run_id = None

    past_run_id = st.text_input("Or paste Run ID", placeholder="full run_id")
    load_btn = st.button("Load Run", use_container_width=True)
    past_run_id = past_run_id or selected_run_id

# ─── State ───────────────────────────────────────────────────────────────────

if "artifacts" not in st.session_state:
    st.session_state["artifacts"] = None
if "run_id" not in st.session_state:
    st.session_state["run_id"] = None
if "errors" not in st.session_state:
    st.session_state["errors"] = []

# ─── Trigger Run ─────────────────────────────────────────────────────────────

if run_btn:
    with st.spinner("Starting business cycle..."):
        try:
            resp = httpx.post(
                f"{API_BASE}/run",
                json={
                    "start_date": str(start_date),
                    "as_of_date": str(as_of_date),
                    "mode": mode,
                    "skip_ingest": skip_ingest,
                },
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            run_id = data["run_id"]
            st.session_state["run_id"] = run_id
            st.session_state["artifacts"] = None
            st.success(f"Run started! Run ID: `{run_id}`")

            # Poll until done
            import time
            progress = st.progress(0, text="Running agents...")
            steps = ["data_engineer", "analyst", "data_scientist", "manager", "worker", "auditor", "persist"]
            for i in range(60):
                time.sleep(3)
                status_resp = httpx.get(f"{API_BASE}/run/{run_id}/status", timeout=5)
                status = status_resp.json().get("status", "running")
                progress.progress(min((i + 1) / 20, 0.95), text=f"Status: {status}")
                if status in ("completed", "failed"):
                    break

            progress.progress(1.0, text="Done!")

            if status == "completed":
                art_resp = httpx.get(f"{API_BASE}/run/{run_id}/artifacts", timeout=10)
                art_resp.raise_for_status()
                st.session_state["artifacts"] = art_resp.json()
            else:
                st.error(f"Run failed: {status_resp.json()}")
        except Exception as exc:
            st.error(f"Could not connect to API: {exc}")
            st.info("Make sure the FastAPI server is running: `uvicorn backend.app.main:app --reload`")

# ─── Load Past Run ───────────────────────────────────────────────────────────

if load_btn and past_run_id:
    with st.spinner("Loading artifacts..."):
        try:
            art_resp = httpx.get(f"{API_BASE}/run/{past_run_id}/artifacts", timeout=10)
            art_resp.raise_for_status()
            st.session_state["artifacts"] = art_resp.json()
            st.session_state["run_id"] = past_run_id
            st.success(f"Loaded run `{past_run_id}`")
        except Exception as exc:
            st.error(f"Failed to load run: {exc}")

# ─── Display Artifacts ───────────────────────────────────────────────────────

artifacts = st.session_state.get("artifacts")
run_id = st.session_state.get("run_id")

if artifacts:
    st.title("Business Cycle Results")

    # Header metadata — read from the artifact itself so loaded runs show correct values
    ar = artifacts.get("analyst_report", {})
    _mode_raw = ar.get("mode", mode)
    _mode = "CUSTOM RANGE" if _mode_raw == "bounded" else "FULL RANGE"
    _start = ar.get("period_start", str(start_date))
    _end = ar.get("period_end", str(as_of_date))

    col1, col2, col3, col4 = st.columns([2, 2, 3, 2])
    with col1:
        st.metric("Run ID", run_id[:8] + "..." if run_id else "—")
    with col2:
        st.metric("Mode", _mode)
    with col3:
        st.metric("Analysis Window", f"{_start} → {_end}")
    with col4:
        try:
            pdf_bytes = generate_report_pdf(artifacts, run_id or "")
            st.download_button(
                label="Download Full Report (PDF)",
                data=pdf_bytes,
                file_name=f"retail_ops_report_{(run_id or 'unknown')[:8]}.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
        except Exception as _pdf_err:
            st.caption(f"PDF unavailable: {_pdf_err}")

    st.markdown("---")

    # Tabs for each agent output
    tabs = st.tabs([
        "Analyst Report",
        "Demand Signal",
        "Manager Decision",
        "Worker Tasks",
        "Audit",
    ])

    with tabs[0]:
        if artifacts.get("analyst_report"):
            show_analyst_report(artifacts["analyst_report"])
        else:
            st.info("No analyst report in this run.")

    with tabs[1]:
        if artifacts.get("forecast_report"):
            show_forecast_report(artifacts["forecast_report"])
        else:
            st.info("No demand signal assessment in this run.")

    with tabs[2]:
        if artifacts.get("decision"):
            show_decision(artifacts["decision"])
        else:
            st.info("No decision in this run.")

    with tabs[3]:
        decision = artifacts.get("decision")
        if decision and artifacts.get("worker_tasks"):
            show_worker_tasks(artifacts.get("worker_tasks", []))
        else:
            st.info("No worker tasks in this run.")

    with tabs[4]:
        if artifacts.get("audit_report"):
            show_audit_report(artifacts["audit_report"])
        else:
            st.info("No audit report in this run.")

else:
    # Landing page
    st.title("Retail Ops Simulator")
    st.markdown("""
    A multi-agent system that simulates a retail business team:

    | Agent | Role |
    |-------|------|
    | **Data Engineer** | Ingest, clean, and validate raw sales data |
    | **Analyst** | KPI reports grounded in SQL queries |
    | **Data Scientist** | Demand forecasting with backtest metrics |
    | **Manager** | Business decisions from reports |
    | **Worker** | Executable task lists from decisions |
    | **Auditor** | Factuality and grounding verification |

    **Get started:** Configure the run settings in the sidebar and click **▶ Run Business Cycle**.

    > Ensure the FastAPI backend is running:
    > ```
    > uvicorn backend.app.main:app --reload
    > ```
    """)

    st.info("Select an as-of date and mode in the sidebar, then click **Run Business Cycle**.")

    st.markdown("#### Dataset")
    st.markdown("""
    The warehouse contains **541,909 invoice rows** from a UK-based e-commerce retailer.

    | | |
    |---|---|
    | **Earliest date** | 1 December 2010 |
    | **Latest date** | 9 December 2011 |
    | **Coverage** | ~13 months |

    Both **Start Date** and **End Date** must fall within this range. The window you select
    defines what data the agents analyse. In bounded mode, agents are strictly limited to
    data within the window — simulating what the business knew at that point in time.
    """)
