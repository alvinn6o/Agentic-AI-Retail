"""Agentic Retail Ops Control Simulator — Streamlit UI."""

from __future__ import annotations

import sys
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import date

import httpx
import streamlit as st

from ui.components.decision_panel import (
    show_audit_report,
    show_control_review,
    show_decision,
    show_dispatch_report,
    show_worker_tasks,
)
from ui.components.enterprise_ui import (
    inject_enterprise_theme,
    render_detail_card,
    render_hero,
    render_section_heading,
    render_sidebar_intro,
    render_summary_card,
    status_pill_html,
)
from ui.components.report_viewer import show_analyst_report, show_forecast_report
from ui.utils.pdf_export import generate_report_pdf

API_BASE = "http://localhost:8000/api/v1"

st.set_page_config(
    page_title="Retail Ops Control Simulator",
    layout="wide",
)
inject_enterprise_theme()


def _tone(value: str) -> str:
    return {
        "bounded": "info",
        "omniscient": "neutral",
        "custom range": "info",
        "full range": "neutral",
        "passed": "success",
        "completed": "success",
        "auto_release": "success",
        "dispatched": "success",
        "running": "info",
        "dry_run": "info",
        "approval_required": "warning",
        "hold_for_approval": "warning",
        "blocked": "danger",
        "failed": "danger",
    }.get(value.lower(), "neutral")


def _render_overview_tab(
    artifacts: dict[str, object],
    run_id: str,
    mode_label: str,
    control_profile: str,
    window_label: str,
) -> None:
    decision = artifacts.get("decision", {}) or {}
    control_review = artifacts.get("control_review", {}) or {}
    audit = artifacts.get("audit_report", {}) or {}
    dispatch = artifacts.get("dispatch_report", {}) or {}
    worker_tasks = artifacts.get("worker_tasks", []) or []

    actions = decision.get("actions", [])
    risks = decision.get("risks", [])
    findings = audit.get("findings", [])
    auto_release = len(control_review.get("auto_releasable_actions", []))
    approvals = len(control_review.get("approval_required_actions", []))
    blocked = len(control_review.get("blocked_actions", []))
    error_count = sum(1 for finding in findings if finding.get("severity") == "error")
    warning_count = sum(1 for finding in findings if finding.get("severity") == "warning")
    dispatch_status = str(dispatch.get("status", "skipped"))
    control_state = str(control_review.get("overall_state", "not_reviewed"))
    audit_state = "passed" if audit.get("passed") is True else ("failed" if audit else "pending")

    render_section_heading(
        "Executive Summary",
        "A consolidated view of decision output, control review, audit status, and enterprise release readiness.",
        eyebrow="Overview",
    )

    cards = st.columns(5)
    with cards[0]:
        render_summary_card("Run Mode", mode_label, "Data-access mode for this run.")
    with cards[1]:
        render_summary_card("Control Profile", control_profile.upper(), "Release-control strictness.")
    with cards[2]:
        render_summary_card("Actions", str(len(actions)), "Manager-proposed actions.")
    with cards[3]:
        render_summary_card("Released Tasks", str(len(worker_tasks)), "Executable tasks after gating.")
    with cards[4]:
        render_summary_card("Audit Errors", str(error_count), "Error-level findings block dispatch.")

    left_col, right_col = st.columns([1.2, 1])

    rationale = str(decision.get("rationale", "") or "")
    rationale_body = escape(rationale).replace("\n", "<br>") if rationale else "No rationale available."

    with left_col:
        render_detail_card(
            "Run Summary",
            (
                "<ul>"
                f"<li><strong>Run ID:</strong> {escape(run_id)}</li>"
                f"<li><strong>Analysis window:</strong> {escape(window_label)}</li>"
                f"<li><strong>Control state:</strong> {escape(control_state.replace('_', ' ').title())}</li>"
                f"<li><strong>Dispatch state:</strong> {escape(dispatch_status.replace('_', ' ').title())}</li>"
                "</ul>"
            ),
            pills=[
                status_pill_html(mode_label, _tone(mode_label.lower())),
                status_pill_html(control_profile.upper(), "info"),
            ],
        )
        render_detail_card("Manager Rationale", rationale_body)

    with right_col:
        render_detail_card(
            "Release Governance",
            (
                "<ul>"
                f"<li><strong>Auto-release:</strong> {auto_release}</li>"
                f"<li><strong>Approval required:</strong> {approvals}</li>"
                f"<li><strong>Blocked:</strong> {blocked}</li>"
                f"<li><strong>Warnings:</strong> {warning_count}</li>"
                "</ul>"
            ),
            pills=[
                status_pill_html(control_state.replace("_", " ").upper(), _tone(control_state)),
                status_pill_html(audit_state.upper(), _tone(audit_state)),
                status_pill_html(dispatch_status.replace("_", " ").upper(), _tone(dispatch_status)),
            ],
        )
        if risks:
            render_detail_card(
                "Declared Risks",
                "<ul>" + "".join(f"<li>{escape(str(risk))}</li>" for risk in risks[:5]) + "</ul>",
            )


def _render_landing_page() -> None:
    render_hero(
        "Controlled Agentic Operations",
        "Run an enterprise-style workflow that combines grounded analytics, deterministic release controls, and enterprise handoff artifacts in one interface.",
        pills=[
            status_pill_html("SQL-GROUNDED", "success"),
            status_pill_html("CONTROL REVIEW", "info"),
            status_pill_html("AUDIT GATED", "warning"),
            status_pill_html("API HANDOFF", "neutral"),
        ],
    )

    render_section_heading(
        "What This Workspace Does",
        "The UI is designed to feel like an internal operations console: run controls on the left, executive summary on top, and detailed artifacts in focused tabs.",
        eyebrow="Welcome",
    )

    cards = st.columns(3)
    with cards[0]:
        render_summary_card("Pipeline", "8 stages", "From ingest to dispatch artifact.")
    with cards[1]:
        render_summary_card("Dataset", "541,909 rows", "UK retail transaction history.")
    with cards[2]:
        render_summary_card("Control Profiles", "2 modes", "Standard and regulated release behavior.")

    left_col, right_col = st.columns([1.1, 1])
    with left_col:
        render_detail_card(
            "How To Use The Tool",
            (
                "<ul>"
                "<li>Select a start date and as-of date in the sidebar.</li>"
                "<li>Choose a data-access mode and control profile.</li>"
                "<li>Launch the workflow and review the executive summary first.</li>"
                "<li>Inspect analyst, decision, control, audit, and handoff tabs as needed.</li>"
                "</ul>"
            ),
        )
    with right_col:
        render_detail_card(
            "Enterprise Design Goals",
            (
                "<ul>"
                "<li>Clear distinction between recommendation, control, audit, and release.</li>"
                "<li>Minimal visual clutter and stronger status hierarchy.</li>"
                "<li>One-click access to the final PDF artifact when available.</li>"
                "</ul>"
            ),
        )

    st.info("Configure the run in the sidebar, then launch the business cycle to populate the dashboard.")


with st.sidebar:
    render_sidebar_intro(
        "Retail Ops Control Simulator",
        "Enterprise-style workspace for bounded analytics, deterministic control review, and downstream task release.",
    )

    st.markdown("### Run Controls")
    st.caption("Dataset range: 1 Dec 2010 to 9 Dec 2011")

    data_min = date(2010, 12, 1)
    data_max = date(2011, 12, 9)

    start_date = st.date_input(
        "Start Date",
        value=date(2011, 4, 1),
        min_value=data_min,
        max_value=data_max,
        help="Beginning of the analysis window.",
    )
    as_of_date = st.date_input(
        "End Date (as-of)",
        value=date(2011, 6, 30),
        min_value=data_min,
        max_value=data_max,
        help="End of the analysis window. In bounded mode, agents cannot see data beyond this date.",
    )

    if start_date >= as_of_date:
        st.error("Start date must be before end date.")

    mode_label = st.radio(
        "Data Access Mode",
        ["Custom Range", "Full Range"],
        index=0,
        help="Custom Range limits the workflow to the selected window. Full Range exposes the complete dataset.",
    )
    mode = "bounded" if mode_label == "Custom Range" else "omniscient"

    control_profile = st.radio(
        "Control Profile",
        ["Standard", "Regulated"],
        index=0,
        help="Regulated adds approval holds and stricter release thresholds.",
    )
    control_profile_value = "regulated" if control_profile == "Regulated" else "standard"

    skip_ingest = st.checkbox(
        "Skip data ingest",
        value=True,
        help="Skip if data is already loaded into DuckDB.",
    )

    run_btn = st.button("Run Business Cycle", type="primary", use_container_width=True)

    st.markdown("### Recent Runs")

    try:
        history_resp = httpx.get(f"{API_BASE}/runs", timeout=5)
        past_runs = history_resp.json() if history_resp.is_success else []
    except Exception:
        past_runs = []

    if past_runs:
        run_options: dict[str, str] = {}
        total = len(past_runs)
        for i, run in enumerate(past_runs):
            run_num = total - i
            start = run.get("period_start") or run.get("as_of_date", "?")
            end = run.get("period_end") or run.get("as_of_date", "?")
            label = f"Run #{run_num}: {start} -> {end} ({run['mode']})"
            run_options[label] = run["run_id"]
        selected_label = st.selectbox(
            "Select a past run",
            options=list(run_options.keys()),
            index=None,
            placeholder="Choose a run...",
        )
        selected_run_id = run_options.get(selected_label) if selected_label else None
    else:
        st.caption("No past runs found.")
        selected_run_id = None

    past_run_id = st.text_input("Or paste Run ID", placeholder="full run_id")
    load_btn = st.button("Load Run", use_container_width=True)
    past_run_id = past_run_id or selected_run_id

if "artifacts" not in st.session_state:
    st.session_state["artifacts"] = None
if "run_id" not in st.session_state:
    st.session_state["run_id"] = None

if run_btn:
    with st.spinner("Launching controlled workflow..."):
        try:
            resp = httpx.post(
                f"{API_BASE}/run",
                json={
                    "start_date": str(start_date),
                    "as_of_date": str(as_of_date),
                    "mode": mode,
                    "control_profile": control_profile_value,
                    "skip_ingest": skip_ingest,
                },
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            run_id = data["run_id"]
            st.session_state["run_id"] = run_id
            st.session_state["artifacts"] = None
            st.success(f"Run started. Run ID: `{run_id}`")

            import time

            progress = st.progress(0, text="Running workflow stages...")
            for i in range(60):
                time.sleep(3)
                status_resp = httpx.get(f"{API_BASE}/run/{run_id}/status", timeout=5)
                status = status_resp.json().get("status", "running")
                progress.progress(min((i + 1) / 20, 0.95), text=f"Workflow status: {status}")
                if status in ("completed", "failed"):
                    break

            progress.progress(1.0, text="Workflow complete")

            if status == "completed":
                art_resp = httpx.get(f"{API_BASE}/run/{run_id}/artifacts", timeout=10)
                art_resp.raise_for_status()
                st.session_state["artifacts"] = art_resp.json()
            else:
                st.error(f"Run failed: {status_resp.json()}")
        except Exception as exc:
            st.error(f"Could not connect to API: {exc}")
            st.info("Make sure the FastAPI server is running: `uvicorn backend.app.main:app --reload`")

if load_btn and past_run_id:
    with st.spinner("Loading run artifacts..."):
        try:
            art_resp = httpx.get(f"{API_BASE}/run/{past_run_id}/artifacts", timeout=10)
            art_resp.raise_for_status()
            st.session_state["artifacts"] = art_resp.json()
            st.session_state["run_id"] = past_run_id
            st.success(f"Loaded run `{past_run_id}`")
        except Exception as exc:
            st.error(f"Failed to load run: {exc}")

artifacts = st.session_state.get("artifacts")
run_id = st.session_state.get("run_id")

if artifacts:
    analyst_report = artifacts.get("analyst_report", {}) or {}
    control_review = artifacts.get("control_review", {}) or {}
    audit_report = artifacts.get("audit_report", {}) or {}
    dispatch_report = artifacts.get("dispatch_report", {}) or {}
    decision = artifacts.get("decision", {}) or {}

    mode_raw = analyst_report.get("mode", mode)
    mode_display = "CUSTOM RANGE" if mode_raw == "bounded" else "FULL RANGE"
    start_label = str(analyst_report.get("period_start", start_date))
    end_label = str(analyst_report.get("period_end", as_of_date))
    window_label = f"{start_label} -> {end_label}"
    control_profile_display = str(control_review.get("control_profile", control_profile_value)).upper()
    audit_state = "PASSED" if audit_report.get("passed") is True else ("FAILED" if audit_report else "PENDING")
    dispatch_state = str(dispatch_report.get("status", "skipped")).replace("_", " ").upper()
    control_state = str(control_review.get("overall_state", "not_reviewed")).replace("_", " ").upper()
    decision_confidence = float(decision.get("confidence", 0) or 0)

    render_hero(
        "Operations Control Board",
        f"Run {run_id[:8]} reviewing {window_label}. Start with the overview tab, then drill into analysis, decisioning, controls, audit, and handoff.",
        pills=[
            status_pill_html(mode_display, _tone(mode_raw)),
            status_pill_html(control_profile_display, "info"),
            status_pill_html(control_state, _tone(control_state)),
            status_pill_html(audit_state, _tone(audit_state)),
            status_pill_html(dispatch_state, _tone(dispatch_state)),
        ],
    )

    top_cards = st.columns(5)
    with top_cards[0]:
        render_summary_card("Run ID", run_id[:8].upper(), "Unique workflow execution reference.")
    with top_cards[1]:
        render_summary_card("Window", window_label, "Analysis interval.")
    with top_cards[2]:
        render_summary_card("Decision Confidence", f"{decision_confidence:.0%}", "Reported manager confidence.")
    with top_cards[3]:
        render_summary_card("Control State", control_state, "Deterministic release outcome.")
    with top_cards[4]:
        render_summary_card("Dispatch", dispatch_state, "Enterprise handoff state.")

    actions_col, export_col = st.columns([1.4, 0.6])
    with actions_col:
        render_detail_card(
            "Run Context",
            (
                "<ul>"
                f"<li><strong>Data mode:</strong> {escape(mode_display)}</li>"
                f"<li><strong>Control profile:</strong> {escape(control_profile_display)}</li>"
                f"<li><strong>Analysis window:</strong> {escape(window_label)}</li>"
                "</ul>"
            ),
        )
    with export_col:
        try:
            pdf_bytes = generate_report_pdf(artifacts, run_id or "")
            st.download_button(
                label="Download Report PDF",
                data=pdf_bytes,
                file_name=f"retail_ops_report_{(run_id or 'unknown')[:8]}.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
        except Exception as pdf_err:
            render_detail_card("PDF Export", escape(f"Unavailable: {pdf_err}"))

    tabs = st.tabs(
        [
            "Overview",
            "Analyst Report",
            "Demand Signal",
            "Manager Decision",
            "Control Review",
            "Worker Tasks",
            "Audit",
            "Enterprise Handoff",
        ]
    )

    with tabs[0]:
        _render_overview_tab(artifacts, run_id, mode_display, control_profile_display, window_label)

    with tabs[1]:
        if artifacts.get("analyst_report"):
            show_analyst_report(artifacts["analyst_report"])
        else:
            st.info("No analyst report in this run.")

    with tabs[2]:
        if artifacts.get("forecast_report"):
            show_forecast_report(artifacts["forecast_report"])
        else:
            st.info("No demand signal assessment in this run.")

    with tabs[3]:
        if artifacts.get("decision"):
            show_decision(artifacts["decision"])
        else:
            st.info("No decision in this run.")

    with tabs[4]:
        if artifacts.get("control_review"):
            show_control_review(artifacts["control_review"])
        else:
            st.info("No control review artifact in this run.")

    with tabs[5]:
        if artifacts.get("worker_tasks"):
            show_worker_tasks(artifacts.get("worker_tasks", []))
        else:
            st.info("No worker tasks in this run.")

    with tabs[6]:
        if artifacts.get("audit_report"):
            show_audit_report(artifacts["audit_report"])
        else:
            st.info("No audit report in this run.")

    with tabs[7]:
        if artifacts.get("dispatch_report"):
            show_dispatch_report(artifacts["dispatch_report"])
        else:
            st.info("No enterprise handoff artifact in this run.")
else:
    _render_landing_page()
