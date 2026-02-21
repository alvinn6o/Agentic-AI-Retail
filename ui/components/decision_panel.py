"""Streamlit components for displaying decisions, tasks, and audit findings."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st


def show_decision(decision: dict[str, Any]) -> None:
    st.subheader("Manager Decision")

    confidence = decision.get("confidence", 0)
    st.metric("Decision Confidence", f"{confidence:.0%}")

    rationale = decision.get("rationale", "")
    if rationale:
        st.markdown("#### Rationale")
        st.write(rationale)

    actions = decision.get("actions", [])
    if actions:
        st.markdown("#### Actions")
        for action in actions:
            urgency = action.get("urgency", "medium")
            color = {"high": "[HIGH]", "medium": "[MED]", "low": "[LOW]"}.get(urgency, "•")
            sku = f" — SKU: `{action['stock_code']}`" if action.get("stock_code") else ""
            st.write(
                f"{color} **{action.get('action_type', '').upper()}**{sku}: "
                f"{action.get('description', '')}"
            )
            if action.get("expected_impact"):
                st.caption(f"  Expected impact: {action['expected_impact']}")

    risks = decision.get("risks", [])
    if risks:
        with st.expander("Risks"):
            for r in risks:
                st.write(f"[!] {r}")


def show_worker_tasks(tasks: list[dict[str, Any]]) -> None:
    st.subheader(f"Worker Tasks ({len(tasks)} tasks)")

    if not tasks:
        st.info("No tasks generated.")
        return

    for task in tasks:
        priority = task.get("priority", "medium")
        icon = {"high": "[HIGH]", "medium": "[MED]", "low": "[LOW]"}.get(priority, "•")
        with st.expander(f"{icon} [{task.get('assigned_to')}] {task.get('title')}"):
            st.write(task.get("description", ""))

            checklist = task.get("checklist", [])
            if checklist:
                st.markdown("**Checklist:**")
                for item in checklist:
                    checked = "[x]" if item.get("completed") else "[ ]"
                    st.write(f"  {checked} {item.get('step')}")

            criteria = task.get("acceptance_criteria", [])
            if criteria:
                st.markdown("**Acceptance Criteria:**")
                for c in criteria:
                    st.write(f"  • {c}")

            if task.get("expected_outcome"):
                st.caption(f"Expected outcome: {task['expected_outcome']}")


def show_audit_report(audit: dict[str, Any]) -> None:
    st.subheader("Audit Report")

    passed = audit.get("passed", True)
    if passed:
        st.success("Audit PASSED — no critical findings")
    else:
        st.error("Audit FAILED — critical findings detected")

    summary = audit.get("summary", "")
    if summary:
        st.write(summary)

    findings = audit.get("findings", [])
    if findings:
        st.markdown("#### Findings")
        for f in findings:
            severity = f.get("severity", "info")
            icon = {"error": "[ERROR]", "warning": "[WARN]", "info": "[INFO]"}.get(severity, "•")
            st.write(
                f"{icon} **{f.get('finding_type', '')}**: {f.get('description', '')}"
            )
            if f.get("recommendation"):
                st.caption(f"  → {f['recommendation']}")
