"""Streamlit components for displaying decisions, tasks, and audit findings."""

from __future__ import annotations

from html import escape
from typing import Any

import streamlit as st

from ui.components.enterprise_ui import (
    render_detail_card,
    render_section_heading,
    render_summary_card,
    status_pill_html,
)


def _urgency_tone(urgency: str) -> str:
    return {
        "high": "danger",
        "medium": "warning",
        "low": "info",
        "error": "danger",
        "warning": "warning",
        "info": "info",
    }.get(urgency, "neutral")


def _control_tone(state: str) -> str:
    return {
        "auto_release": "success",
        "hold_for_approval": "warning",
        "blocked": "danger",
    }.get(state, "neutral")


def show_decision(decision: dict[str, Any]) -> None:
    render_section_heading(
        "Manager Decision",
        "Recommended actions, rationale, and declared risk posture for this run.",
        eyebrow="Decisioning",
    )

    confidence = decision.get("confidence", 0)
    actions = decision.get("actions", [])
    risks = decision.get("risks", [])

    col1, col2, col3 = st.columns(3)
    with col1:
        render_summary_card("Decision Confidence", f"{confidence:.0%}", "Confidence reported by the manager agent.")
    with col2:
        render_summary_card("Actions Proposed", str(len(actions)), "Potential actions before control gating.")
    with col3:
        render_summary_card("Declared Risks", str(len(risks)), "Risks surfaced by the manager output.")

    rationale = decision.get("rationale", "")
    if rationale:
        render_detail_card("Rationale", escape(rationale).replace("\n", "<br>"))

    if actions:
        render_section_heading(
            "Recommended Actions",
            "Action cards retain urgency, target scope, and expected impact for downstream control review.",
            eyebrow="Action Queue",
        )
        for action in actions:
            urgency = action.get("urgency", "medium")
            meta_parts = [
                f"Type: {escape(action.get('action_type', '').upper())}",
                f"SKU: {escape(str(action.get('stock_code') or '-'))}",
                f"Category: {escape(str(action.get('category') or '-'))}",
            ]
            if action.get("quantity") is not None:
                meta_parts.append(f"Quantity: {action.get('quantity')}")
            render_detail_card(
                action.get("description", "Recommended action"),
                escape(action.get("expected_impact", "No expected impact supplied.")),
                meta=" | ".join(meta_parts),
                pills=[status_pill_html(urgency.upper(), _urgency_tone(urgency))],
            )

    if risks:
        render_section_heading(
            "Declared Risks",
            "Risks captured alongside the manager recommendation.",
            eyebrow="Risk Register",
        )
        for risk in risks:
            render_detail_card("Risk", escape(risk), pills=[status_pill_html("REVIEW", "warning")])


def show_worker_tasks(tasks: list[dict[str, Any]]) -> None:
    render_section_heading(
        "Worker Tasks",
        "Executable tasks generated only from actions released by the control layer.",
        eyebrow="Execution",
    )
    render_summary_card("Released Tasks", str(len(tasks)), "Tasks available for operational teams.")

    if not tasks:
        st.info("No tasks generated.")
        return

    for task in tasks:
        priority = task.get("priority", "medium")
        with st.expander(f"{task.get('title')} | {task.get('assigned_to')}"):
            render_detail_card(
                task.get("title", "Worker task"),
                escape(task.get("description", "")),
                meta=(
                    f"Assigned to: {escape(str(task.get('assigned_to') or '-'))} | "
                    f"Task ID: {escape(str(task.get('task_id') or '-'))}"
                ),
                pills=[status_pill_html(priority.upper(), _urgency_tone(priority))],
            )

            checklist = task.get("checklist", [])
            if checklist:
                st.markdown("**Checklist**")
                for item in checklist:
                    checked = "[x]" if item.get("completed") else "[ ]"
                    st.write(f"  {checked} {item.get('step')}")

            criteria = task.get("acceptance_criteria", [])
            if criteria:
                st.markdown("**Acceptance Criteria**")
                for c in criteria:
                    st.write(f"  • {c}")

            if task.get("expected_outcome"):
                st.caption(f"Expected outcome: {task['expected_outcome']}")


def show_control_review(review: dict[str, Any]) -> None:
    render_section_heading(
        "Control Review",
        "Deterministic approval and blocking logic applied after decision generation and before execution.",
        eyebrow="Release Governance",
    )

    overall_state = review.get("overall_state", "auto_release")
    summary = review.get("summary", "")
    col1, col2, col3 = st.columns(3)
    with col1:
        render_summary_card("Auto-release", str(len(review.get("auto_releasable_actions", []))), "Actions released automatically.")
    with col2:
        render_summary_card("Approval Required", str(len(review.get("approval_required_actions", []))), "Actions held for human approval.")
    with col3:
        render_summary_card("Blocked", str(len(review.get("blocked_actions", []))), "Actions blocked pending manual review.")

    render_detail_card(
        "Overall Control State",
        escape(summary or "No control summary available."),
        pills=[status_pill_html(overall_state.replace("_", " ").upper(), _control_tone(overall_state))],
    )

    for action_review in review.get("action_reviews", []):
        title = (
            f"Action #{action_review.get('action_index', 0) + 1} "
            f"{action_review.get('action_type', '').upper()}"
        )
        state = action_review.get("execution_state", "unknown")
        meta = (
            f"Risk tier: {escape(action_review.get('risk_tier', 'unknown'))} | "
            f"Approval role: {escape(action_review.get('approval_role', 'none'))}"
        )
        body = escape(action_review.get("description", ""))
        with st.expander(title):
            render_detail_card(
                title,
                body,
                meta=meta,
                pills=[status_pill_html(state.replace("_", " ").upper(), _control_tone(state))],
            )
            for reason in action_review.get("reasons", []):
                st.write(f"- {reason}")
            citations = action_review.get("policy_citations", [])
            if citations:
                st.markdown("**Policy citations**")
                for citation in citations:
                    st.write(
                        f"- `{citation.get('control_id', '')}` in `{citation.get('source', '')}`: "
                        f"{citation.get('summary', '')}"
                    )


def show_audit_report(audit: dict[str, Any]) -> None:
    render_section_heading(
        "Audit Report",
        "Factuality, policy, and completeness checks performed before any enterprise release.",
        eyebrow="Quality Assurance",
    )

    passed = audit.get("passed", True)
    summary = audit.get("summary", "")
    findings = audit.get("findings", [])
    error_count = sum(1 for finding in findings if finding.get("severity") == "error")
    warning_count = sum(1 for finding in findings if finding.get("severity") == "warning")
    info_count = sum(1 for finding in findings if finding.get("severity") == "info")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        render_summary_card("Audit Status", "PASSED" if passed else "FAILED", "Dispatch only proceeds when audit passes.")
    with col2:
        render_summary_card("Errors", str(error_count), "Critical findings.")
    with col3:
        render_summary_card("Warnings", str(warning_count), "Follow-up required.")
    with col4:
        render_summary_card("Info", str(info_count), "Observational findings.")

    render_detail_card(
        "Audit Summary",
        escape(summary or "No audit summary available."),
        pills=[status_pill_html("PASS" if passed else "FAIL", "success" if passed else "danger")],
    )

    if findings:
        render_section_heading(
            "Audit Findings",
            "Findings are ordered in the artifact as produced by the auditor.",
            eyebrow="Exceptions",
        )
        for f in findings:
            severity = f.get("severity", "info")
            render_detail_card(
                f.get("finding_type", "Finding").replace("_", " ").title(),
                escape(f.get("description", "")),
                meta=f"Affected field: {escape(f.get('affected_field', '-') or '-')}",
                pills=[status_pill_html(severity.upper(), _urgency_tone(severity))],
            )
            if f.get("recommendation"):
                st.caption(f"  → {f['recommendation']}")


def show_dispatch_report(report: dict[str, Any]) -> None:
    render_section_heading(
        "Enterprise Handoff",
        "Prepared or dispatched task payloads for downstream operational systems.",
        eyebrow="Integration",
    )

    status = report.get("status", "skipped")
    summary = report.get("summary", "")
    tone = {
        "dispatched": "success",
        "dry_run": "info",
        "approval_required": "warning",
        "blocked": "danger",
        "failed": "danger",
    }.get(status, "neutral")

    col1, col2, col3 = st.columns(3)
    with col1:
        render_summary_card("Dispatch Status", status.replace("_", " ").upper(), "Current outbound release state.")
    with col2:
        render_summary_card("Target System", str(report.get("target_system", "-")).upper(), "Configured enterprise destination.")
    with col3:
        render_summary_card("Records", str(len(report.get("records", []))), "Prepared or attempted payloads.")

    render_detail_card(
        "Dispatch Summary",
        escape(summary or "No dispatch summary available."),
        pills=[status_pill_html(status.replace("_", " ").upper(), tone)],
    )

    for record in report.get("records", []):
        record_status = record.get("status", "")
        with st.expander(
            f"{record.get('title', '')} -> {record.get('target_system', '')}"
        ):
            render_detail_card(
                record.get("title", "Dispatch record"),
                escape(record.get("reason", "Payload prepared for handoff.") or "Payload prepared for handoff."),
                meta=(
                    f"Task ID: {escape(str(record.get('task_id') or '-'))} | "
                    f"Assigned to: {escape(str(record.get('assigned_to') or '-'))}"
                ),
                pills=[status_pill_html(record_status.upper(), _urgency_tone(record_status))],
            )
            endpoint = record.get("endpoint", "")
            if endpoint:
                st.write(f"Endpoint: `{endpoint}`")
            payload = record.get("payload")
            if payload:
                st.json(payload)
