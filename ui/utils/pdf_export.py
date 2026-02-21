"""Generate an executive business-style PDF report from run artifacts.

Structure (per README_claude_business_report.md):
  Cover -> Executive Summary -> Business Context -> Performance Snapshot
  -> Key Insights -> Forecasting Assessment -> Action Plan
  -> Risks & Next Steps -> Appendix
"""

from __future__ import annotations

from typing import Any

from fpdf import FPDF


# ─── Text helpers ─────────────────────────────────────────────────────────────

_UNICODE_SUBS: dict[str, str] = {
    "\u2014": "--",
    "\u2013": "-",
    "\u2019": "'",
    "\u2018": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2022": "-",
    "\u2192": "->",
    "\u2190": "<-",
    "\u00a3": "GBP",
    "\u2026": "...",
}


def _sanitize(text: str) -> str:
    for char, replacement in _UNICODE_SUBS.items():
        text = text.replace(char, replacement)
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _safe(v: Any, default: str = "-") -> str:
    if v is None:
        return default
    s = str(v).strip()
    return _sanitize(s) if s else default


def _currency(v: Any) -> str:
    try:
        return f"GBP {float(v):,.0f}"
    except (TypeError, ValueError):
        return _safe(v)


def _currency2(v: Any) -> str:
    """Two decimal places."""
    try:
        return f"GBP {float(v):,.2f}"
    except (TypeError, ValueError):
        return _safe(v)


def _pct(v: Any, default: str = "N/A") -> str:
    try:
        return f"{float(v):.1%}"
    except (TypeError, ValueError):
        return default


def _num(v: Any, decimals: int = 1) -> str:
    try:
        fmt = f"{{:,.{decimals}f}}"
        return fmt.format(float(v))
    except (TypeError, ValueError):
        return _safe(v)


# ─── PDF class ────────────────────────────────────────────────────────────────

class _PDF(FPDF):

    def __init__(self, run_id: str, period: str) -> None:
        super().__init__()
        self.run_id = run_id
        self.period = period
        self.set_auto_page_break(auto=True, margin=22)
        self.set_margins(left=18, top=20, right=18)

    def normalize_text(self, text: str) -> str:  # type: ignore[override]
        return super().normalize_text(_sanitize(text))

    # ── Header / footer ───────────────────────────────────────────────────

    def header(self) -> None:
        if self.page_no() == 1:
            return  # cover page has no header
        self.set_font("Helvetica", style="B", size=8)
        self.set_text_color(140, 140, 140)
        self.cell(0, 5, f"Retail Ops Business Report  |  {self.period}", align="L")
        self.ln(8)
        self.set_text_color(0, 0, 0)

    def footer(self) -> None:
        self.set_y(-14)
        self.set_font("Helvetica", size=8)
        self.set_text_color(160, 160, 160)
        self.cell(0, 5, f"Run {self.run_id[:8]}  |  Page {self.page_no()}", align="C")
        self.set_text_color(0, 0, 0)

    # ── Layout primitives ─────────────────────────────────────────────────

    def section_title(self, title: str) -> None:
        self.ln(2)
        self.set_font("Helvetica", style="B", size=13)
        self.set_fill_color(28, 62, 140)
        self.set_text_color(255, 255, 255)
        self.cell(0, 9, f"  {title}", fill=True, ln=True)
        self.set_text_color(0, 0, 0)
        self.ln(3)

    def sub_title(self, title: str) -> None:
        self.ln(1)
        self.set_font("Helvetica", style="B", size=10)
        self.set_text_color(28, 62, 140)
        self.cell(0, 7, title, ln=True)
        self.set_text_color(0, 0, 0)

    def body(self, text: str, size: int = 10) -> None:
        self.set_font("Helvetica", size=size)
        self.set_x(self.l_margin)
        self.multi_cell(self.epw, 5.5, text)

    def body_italic(self, text: str, size: int = 9) -> None:
        self.set_font("Helvetica", style="I", size=size)
        self.set_x(self.l_margin)
        self.multi_cell(self.epw, 5, text)

    def bullet(self, text: str, indent: int = 8) -> None:
        self.set_font("Helvetica", size=10)
        x0 = self.l_margin + indent
        self.set_x(x0)
        self.multi_cell(self.epw - indent, 5.5, f"-  {text}")

    def kv(self, key: str, value: str, label_w: int = 52) -> None:
        self.set_font("Helvetica", style="B", size=10)
        self.cell(label_w, 6, f"{key}:", ln=False)
        self.set_font("Helvetica", size=10)
        self.multi_cell(self.epw - label_w, 6, value)

    def rule(self, color: tuple[int, int, int] = (200, 200, 200)) -> None:
        self.set_draw_color(*color)
        y = self.get_y()
        self.line(self.l_margin, y, self.l_margin + self.epw, y)
        self.ln(3)

    def thin_rule(self) -> None:
        self.rule((220, 220, 220))

    def table_header(self, cols: list[tuple[str, int]]) -> None:
        self.set_font("Helvetica", style="B", size=8)
        self.set_fill_color(28, 62, 140)
        self.set_text_color(255, 255, 255)
        for label, w in cols:
            self.cell(w, 7, label, fill=True)
        self.ln()
        self.set_text_color(0, 0, 0)

    def table_row(self, cols: list[tuple[str, int]], shade: bool = False) -> None:
        self.set_font("Helvetica", size=8)
        bg = (245, 248, 255) if shade else (255, 255, 255)
        self.set_fill_color(*bg)
        for text, w in cols:
            self.cell(w, 6, _sanitize(str(text))[:72], fill=True)
        self.ln()

    def severity_label(self, sev: str) -> None:
        """Inline colored severity badge then reset."""
        colours = {
            "error": (200, 30, 30),
            "warning": (180, 100, 0),
            "info": (40, 100, 180),
        }
        r, g, b = colours.get(sev.lower(), (80, 80, 80))
        self.set_font("Helvetica", style="B", size=8)
        self.set_text_color(r, g, b)
        self.cell(28, 5, f"[{sev.upper()}]", ln=False)
        self.set_text_color(0, 0, 0)


# ─── Data helpers ─────────────────────────────────────────────────────────────

def _kpi_lookup(kpis: list[dict], *names: str) -> str | None:
    """Return the value string for the first matching KPI name (case-insensitive)."""
    lower_names = {n.lower() for n in names}
    for kpi in kpis:
        if kpi.get("name", "").lower() in lower_names:
            v = kpi.get("value")
            unit = kpi.get("unit", "")
            if unit in ("GBP", "gbp"):
                return _currency(v)
            try:
                return f"{float(v):,.1f}"
            except (TypeError, ValueError):
                return _safe(v)
    return None


def _assess_forecast(backtest: list[dict]) -> tuple[bool, str]:
    """Return (is_reliable, prose_assessment)."""
    if not backtest:
        return False, (
            "No backtest metrics were produced. The forecast model could not be "
            "evaluated against historical data and should not be used for planning."
        )
    valid = [m for m in backtest if m.get("mape") is not None]
    if not valid:
        return False, (
            "Backtest metrics are incomplete (MAPE values missing for all series). "
            "The model cannot be considered reliable at this time."
        )
    avg_mape = sum(m["mape"] for m in valid) / len(valid)
    high_mape = [m for m in valid if m["mape"] > 0.5]
    if avg_mape > 0.5 or len(high_mape) > len(valid) * 0.5:
        return False, (
            f"The seasonal-naive model shows an average MAPE of {avg_mape:.1%} across "
            f"{len(valid)} SKU series, with {len(high_mape)} series exceeding 50% error. "
            "This level of error is not acceptable for operational planning. Contributing "
            "factors include sparse demand (many zero-fill days) and excluded returns. "
            "Forecasts should be treated as directional only until model governance "
            "and data-quality issues are resolved."
        )
    return True, (
        f"The seasonal-naive model achieves an average MAPE of {avg_mape:.1%} across "
        f"{len(valid)} SKU series. While directionally useful, uncertainty bands should "
        "be reviewed before committing to reorder quantities."
    )


def _top_audit_findings(findings: list[dict], n: int = 5) -> list[dict]:
    """Return up to n findings, errors first then warnings then info."""
    order = {"error": 0, "warning": 1, "info": 2}
    return sorted(findings, key=lambda f: order.get(f.get("severity", "info"), 3))[:n]


def _action_plan_rows(
    actions: list[dict], tasks: list[dict]
) -> list[dict[str, str]]:
    """
    Merge decision actions with worker tasks to produce a unified action-plan table.
    Each action is matched to a worker task by action_type similarity.
    """
    # Build a quick lookup: action_type -> first matching worker task
    task_map: dict[str, dict] = {}
    for t in tasks:
        key = t.get("action_type", "").lower()
        if key and key not in task_map:
            task_map[key] = t

    rows = []
    for a in actions:
        atype = a.get("action_type", "").lower()
        matched = task_map.get(atype, {})
        rows.append({
            "action": _safe(a.get("description")),
            "priority": _safe(a.get("urgency", "medium")).upper(),
            "owner": _safe(matched.get("assigned_to") or "-"),
            "due": _safe(matched.get("due_date") or "-"),
            "impact": _safe(a.get("expected_impact") or matched.get("expected_outcome") or "-"),
        })
    return rows


# ─── Page renderers ───────────────────────────────────────────────────────────

def _page_cover(pdf: _PDF, artifacts: dict[str, Any], run_id: str, period: str) -> None:
    pdf.add_page()
    pdf.ln(28)

    # Decorative top bar
    pdf.set_fill_color(28, 62, 140)
    pdf.rect(18, pdf.get_y(), pdf.epw, 2, "F")
    pdf.ln(10)

    pdf.set_font("Helvetica", style="B", size=26)
    pdf.set_text_color(28, 62, 140)
    pdf.cell(0, 12, "Business Cycle Report", align="C", ln=True)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(4)

    ar = artifacts.get("analyst_report", {})
    mode_raw = ar.get("mode", "")
    mode_label = "Custom Range" if mode_raw == "bounded" else "Full Range"

    pdf.set_font("Helvetica", size=13)
    pdf.set_text_color(60, 60, 60)
    pdf.cell(0, 8, f"Analysis Period:  {period}", align="C", ln=True)
    pdf.cell(0, 7, f"Data Access Mode:  {mode_label}", align="C", ln=True)
    pdf.ln(4)
    pdf.set_font("Helvetica", size=9)
    pdf.set_text_color(130, 130, 130)
    pdf.cell(0, 6, f"Run ID: {run_id}", align="C", ln=True)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(18)

    # Bottom bar
    pdf.set_fill_color(28, 62, 140)
    pdf.rect(18, pdf.get_y(), pdf.epw, 2, "F")
    pdf.ln(10)

    pdf.set_font("Helvetica", size=10)
    pdf.body(
        "Prepared by the Retail Ops Simulator. This report summarises automated analysis "
        "of sales data, demand forecasting, operational decisions, and data quality "
        "findings for the period shown above. For raw data tables and full task checklists "
        "see the Appendix section at the end of this document."
    )


def _page_exec_summary(
    pdf: _PDF,
    ar: dict,
    decision: dict,
    audit: dict,
) -> None:
    pdf.add_page()
    pdf.section_title("1.  Executive Summary")

    kpis = ar.get("kpis", [])

    # Period / mode line
    mode_raw = ar.get("mode", "")
    mode_label = "Custom Range" if mode_raw == "bounded" else "Full Range"
    period_start = _safe(ar.get("period_start"))
    period_end = _safe(ar.get("period_end"))
    pdf.bullet(f"Analysis period: {period_start} to {period_end}  ({mode_label})")

    # Revenue / volume bullets
    revenue = _kpi_lookup(kpis, "total_revenue", "revenue", "total revenue")
    if revenue:
        pdf.bullet(f"Total revenue: {revenue}")

    orders = _kpi_lookup(kpis, "total_orders", "orders", "order_count", "num_orders")
    if orders:
        pdf.bullet(f"Total orders: {orders}")

    customers = _kpi_lookup(kpis, "unique_customers", "customers", "customer_count")
    if customers:
        pdf.bullet(f"Unique customers: {customers}")

    aov = _kpi_lookup(kpis, "avg_order_value", "average_order_value", "aov")
    if aov:
        pdf.bullet(f"Average order value: {aov}")

    # Key issues from anomalies + audit
    anomalies = ar.get("anomalies", [])
    high_anomalies = [a for a in anomalies if a.get("severity") == "high"][:2]
    for a in high_anomalies:
        pdf.bullet(f"Issue: {_safe(a.get('description'))}")

    findings = audit.get("findings", [])
    error_findings = [f for f in findings if f.get("severity") == "error"][:2]
    for f in error_findings:
        pdf.bullet(f"Data quality: {_safe(f.get('description'))[:100]}")

    # Top recommended actions
    actions = decision.get("actions", [])
    high_actions = sorted(actions, key=lambda a: {"high": 0, "medium": 1, "low": 2}.get(a.get("urgency", "low"), 3))
    pdf.ln(2)
    pdf.sub_title("Recommended Actions (Priority Order)")
    for a in high_actions[:5]:
        urgency = _safe(a.get("urgency", "medium")).upper()
        pdf.bullet(f"[{urgency}] {_safe(a.get('description'))}")

    # Confidence
    conf = decision.get("confidence")
    if conf is not None:
        pdf.ln(2)
        pdf.body_italic(f"Decision confidence: {_pct(conf)}  |  Audit status: {'PASSED' if audit.get('passed') else 'FAILED'}")


def _page_business_context(pdf: _PDF, ar: dict, decision: dict) -> None:
    pdf.add_page()
    pdf.section_title("2.  Business Context & Objective")

    mode_raw = ar.get("mode", "")
    period_start = _safe(ar.get("period_start"))
    period_end = _safe(ar.get("period_end"))
    mode_desc = (
        "bounded (agents restricted to data within the analysis window, "
        "simulating real-time operational constraints)"
        if mode_raw == "bounded"
        else "omniscient (full dataset available, used for benchmarking)"
    )

    pdf.body(
        f"This analysis covers the period from {period_start} to {period_end} "
        f"using {mode_desc} data access. "
        "The objective was to assess recent trading performance, identify inventory "
        "and operational risks, produce a short-term demand forecast, and generate a "
        "prioritised action plan for the operations team."
    )
    pdf.ln(4)

    narrative = ar.get("narrative", "")
    if narrative:
        pdf.sub_title("Analysis Narrative")
        pdf.body(narrative)

    rationale = decision.get("rationale", "")
    if rationale:
        pdf.ln(3)
        pdf.sub_title("Decision Rationale")
        pdf.body(rationale)


def _page_performance_snapshot(pdf: _PDF, ar: dict) -> None:
    pdf.add_page()
    pdf.section_title("3.  Performance Snapshot")

    kpis = ar.get("kpis", [])
    if kpis:
        col_defs = [("Metric", 90), ("Value", 60), ("Unit", 24)]
        pdf.table_header(col_defs)
        for idx, kpi in enumerate(kpis):
            val = kpi.get("value")
            unit = _safe(kpi.get("unit"), "")
            if unit in ("GBP", "gbp"):
                display = _currency2(val)
            else:
                try:
                    display = f"{float(val):,.2f}"
                except (TypeError, ValueError):
                    display = _safe(val)
            pdf.table_row(
                [
                    (_safe(kpi.get("name", "").replace("_", " ").title()), 90),
                    (display, 60),
                    (unit if unit not in ("GBP", "gbp") else "", 24),
                ],
                shade=idx % 2 == 1,
            )
        pdf.ln(4)

    # Interpretation note
    pdf.body_italic(
        "Values above are derived from SQL queries against the curated sales data. "
        "Return rate is calculated as negative-quantity lines divided by total invoiced "
        "lines. Average order value reflects revenue per distinct invoice."
    )


def _page_key_insights(pdf: _PDF, ar: dict) -> None:
    pdf.add_page()
    pdf.section_title("4.  Key Insights")

    # Top SKUs table (top 10, ordered by revenue desc)
    top_skus = ar.get("top_skus", [])
    if top_skus:
        pdf.sub_title("Top 10 SKUs by Revenue")
        skus_sorted = sorted(
            top_skus,
            key=lambda x: float(x.get("total_revenue") or 0),
            reverse=True,
        )[:10]

        # Calculate top-5 total for share computation
        top5_total = sum(float(s.get("total_revenue") or 0) for s in skus_sorted[:5])

        col_defs = [("Rank", 14), ("Stock Code", 34), ("Description", 70), ("Revenue", 34), ("Units", 22)]
        pdf.table_header(col_defs)
        for idx, sku in enumerate(skus_sorted):
            rev = float(sku.get("total_revenue") or 0)
            units = sku.get("total_units")
            units_str = f"{int(float(units)):,}" if units is not None else "-"
            pdf.table_row(
                [
                    (str(idx + 1), 14),
                    (_safe(sku.get("stock_code")), 34),
                    (_safe(sku.get("description"))[:42], 70),
                    (_currency(rev), 34),
                    (units_str, 22),
                ],
                shade=idx % 2 == 1,
            )
        pdf.ln(3)

        if top5_total > 0:
            pdf.body_italic(
                f"Top 5 SKUs account for GBP {top5_total:,.0f} combined revenue. "
                "Concentration in a small number of SKUs represents both an opportunity "
                "and a supply-chain dependency risk."
            )
        pdf.ln(3)

    # Data quality anomalies
    anomalies = ar.get("anomalies", [])
    if anomalies:
        pdf.sub_title("Data Quality & Anomalies")
        for a in anomalies:
            sev = _safe(a.get("severity"), "info")
            pdf.severity_label(sev)
            pdf.set_font("Helvetica", size=9)
            self_x = pdf.l_margin + 30
            pdf.set_x(self_x)
            pdf.multi_cell(pdf.epw - 30, 5, _safe(a.get("description")))
            pdf.set_x(pdf.l_margin)
        pdf.ln(2)


def _page_forecast(pdf: _PDF, report: dict) -> None:
    if not report:
        return
    pdf.add_page()
    pdf.section_title("5.  Demand Signal Assessment")

    model = _safe(report.get("model_name"))
    horizon = _safe(report.get("horizon_days"))
    pdf.kv("Model", model)
    pdf.kv("Forecast horizon", f"{horizon} days")
    pdf.ln(4)

    backtest = report.get("backtest_metrics", [])
    is_reliable, assessment = _assess_forecast(backtest)

    # Reliability verdict
    pdf.set_font("Helvetica", style="B", size=10)
    if is_reliable:
        pdf.set_text_color(0, 130, 0)
        pdf.cell(0, 7, "Model assessment: USABLE (within acceptable error bounds)", ln=True)
    else:
        pdf.set_text_color(180, 30, 30)
        pdf.cell(0, 7, "Model assessment: NOT RELIABLE -- do not use for operational planning", ln=True)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(2)
    pdf.body(assessment)
    pdf.ln(4)

    # Backtest metrics table (compact)
    if backtest:
        pdf.sub_title("Backtest Metrics by SKU")
        col_defs = [("SKU", 44), ("MAPE", 34), ("RMSE", 34), ("Train Window", 62)]
        pdf.table_header(col_defs)
        for idx, m in enumerate(backtest[:15]):
            mape = m.get("mape")
            rmse = m.get("rmse")
            train = f"{_safe(m.get('train_start'))} to {_safe(m.get('train_end'))}"
            mape_str = _pct(mape)
            rmse_str = f"{float(rmse):.2f}" if rmse is not None else "N/A"
            # Highlight high MAPE rows
            if mape is not None and mape > 0.5:
                pdf.set_fill_color(255, 235, 235)
            elif idx % 2 == 1:
                pdf.set_fill_color(245, 248, 255)
            else:
                pdf.set_fill_color(255, 255, 255)
            pdf.set_font("Helvetica", size=8)
            pdf.cell(44, 6, _safe(m.get("stock_code")), fill=True)
            pdf.cell(34, 6, mape_str, fill=True)
            pdf.cell(34, 6, rmse_str, fill=True)
            pdf.cell(62, 6, train, fill=True)
            pdf.ln()
        pdf.ln(3)
        pdf.body_italic(
            "Rows highlighted in red exceed 50% MAPE. "
            "Raw per-day forecast values are available in the Appendix."
        )

    assumptions = report.get("assumptions", [])
    if assumptions:
        pdf.ln(3)
        pdf.sub_title("Model Assumptions")
        for a in assumptions:
            pdf.bullet(_safe(a))


def _page_action_plan(pdf: _PDF, decision: dict, tasks: list[dict]) -> None:
    if not decision:
        return
    pdf.add_page()
    pdf.section_title("6.  Decisions & Action Plan")

    conf = decision.get("confidence")
    if conf is not None:
        pdf.kv("Decision confidence", _pct(conf))
        pdf.ln(3)

    rows = _action_plan_rows(decision.get("actions", []), tasks)
    if rows:
        # Column widths must sum to epw (174)
        col_defs = [
            ("Action", 64),
            ("Priority", 20),
            ("Owner", 34),
            ("Due", 24),
            ("Expected Impact", 32),
        ]
        pdf.table_header(col_defs)
        for idx, row in enumerate(rows):
            action_text = row["action"][:60]
            impact_text = row["impact"][:30]
            shade = idx % 2 == 1
            bg = (245, 248, 255) if shade else (255, 255, 255)
            pdf.set_fill_color(*bg)
            pdf.set_font("Helvetica", size=8)
            pdf.cell(64, 6, action_text, fill=True)
            # Colour-code priority
            pri = row["priority"]
            pri_colours = {"HIGH": (200, 0, 0), "MEDIUM": (160, 100, 0), "LOW": (0, 120, 0)}
            r, g, b = pri_colours.get(pri, (60, 60, 60))
            pdf.set_text_color(r, g, b)
            pdf.set_font("Helvetica", style="B", size=8)
            pdf.cell(20, 6, pri, fill=True)
            pdf.set_text_color(0, 0, 0)
            pdf.set_font("Helvetica", size=8)
            pdf.cell(34, 6, row["owner"][:18], fill=True)
            pdf.cell(24, 6, row["due"][:12], fill=True)
            pdf.cell(32, 6, impact_text, fill=True)
            pdf.ln()
        pdf.ln(4)

    risks = decision.get("risks", [])
    if risks:
        pdf.sub_title("Decision Risks")
        for r in risks:
            pdf.bullet(_safe(r))


def _page_risks(pdf: _PDF, decision: dict, audit: dict) -> None:
    pdf.add_page()
    pdf.section_title("7.  Risks, Limitations & Next Steps")

    pdf.sub_title("Data Integrity Risks")
    findings = audit.get("findings", [])
    top_findings = _top_audit_findings(findings, n=5)
    if top_findings:
        for f in top_findings:
            sev = _safe(f.get("severity"), "info")
            pdf.severity_label(sev)
            desc = _safe(f.get("description"))
            rec = f.get("recommendation")
            pdf.set_font("Helvetica", size=9)
            pdf.set_x(pdf.l_margin + 30)
            pdf.multi_cell(pdf.epw - 30, 5, desc)
            if rec:
                pdf.set_font("Helvetica", style="I", size=9)
                pdf.set_x(pdf.l_margin + 30)
                pdf.multi_cell(pdf.epw - 30, 5, f"-> {_safe(rec)}")
            pdf.set_x(pdf.l_margin)
            pdf.ln(1)
    else:
        pdf.body("No significant data-quality findings recorded.")

    pdf.ln(4)
    pdf.sub_title("Forecast Model Risk")
    pdf.body(
        "The seasonal-naive model relies on historical weekly patterns. It does not "
        "account for promotions, new product introductions, or macro events. Until "
        "MAPE values fall below 30% across core SKUs, forecast outputs should be used "
        "for directional planning only and not for automated reorder triggers."
    )

    pdf.ln(4)
    pdf.sub_title("Governance & Process Improvements")
    pdf.bullet("Resolve negative-quantity and zero-revenue anomalies in source data before next cycle.")
    pdf.bullet("Introduce weekly data-quality checks as a standing operational process.")
    pdf.bullet("Evaluate Prophet or LightGBM models as alternatives to seasonal-naive.")
    pdf.bullet("Define ownership and SLAs for each action in the Action Plan table.")
    pdf.bullet("Schedule a follow-up review at the end of the next business cycle.")

    # Audit summary if present
    summary = audit.get("summary", "")
    if summary:
        pdf.ln(4)
        pdf.sub_title("Audit Summary")
        pdf.body(summary)


def _page_appendix(
    pdf: _PDF,
    ar: dict,
    forecast: dict,
    tasks: list[dict],
    audit: dict,
) -> None:
    pdf.add_page()
    pdf.section_title("Appendix -- Supporting Data")

    # A. Full KPI table
    kpis = ar.get("kpis", [])
    if kpis:
        pdf.sub_title("A.  Full KPI Table")
        col_defs = [("Metric", 90), ("Value", 56), ("Unit", 28)]
        pdf.table_header(col_defs)
        for idx, kpi in enumerate(kpis):
            val = kpi.get("value")
            unit = _safe(kpi.get("unit"), "")
            if unit in ("GBP", "gbp"):
                display = _currency2(val)
            else:
                try:
                    display = f"{float(val):,.4f}"
                except (TypeError, ValueError):
                    display = _safe(val)
            pdf.table_row(
                [
                    (_safe(kpi.get("name", "").replace("_", " ").title()), 90),
                    (display, 56),
                    (unit, 28),
                ],
                shade=idx % 2 == 1,
            )
        pdf.ln(4)

    # B. Full SKU list
    top_skus = ar.get("top_skus", [])
    if top_skus:
        pdf.sub_title("B.  Full SKU Revenue Table")
        skus_sorted = sorted(
            top_skus,
            key=lambda x: float(x.get("total_revenue") or 0),
            reverse=True,
        )
        col_defs = [("Stock Code", 34), ("Description", 86), ("Revenue (GBP)", 34), ("Units", 20)]
        pdf.table_header(col_defs)
        for idx, sku in enumerate(skus_sorted):
            units = sku.get("total_units")
            units_str = f"{int(float(units)):,}" if units is not None else "-"
            pdf.table_row(
                [
                    (_safe(sku.get("stock_code")), 34),
                    (_safe(sku.get("description"))[:52], 86),
                    (_currency(sku.get("total_revenue")), 34),
                    (units_str, 20),
                ],
                shade=idx % 2 == 1,
            )
        pdf.ln(4)

    # C. Forecast data sample
    forecasts = forecast.get("forecasts", [])
    if forecasts:
        pdf.sub_title("C.  Demand Signal Data Sample (first 30 rows)")
        col_defs = [("SKU", 40), ("Date", 36), ("Predicted Qty", 36), ("Lower", 31), ("Upper", 31)]
        pdf.table_header(col_defs)
        for idx, f in enumerate(forecasts[:30]):
            yhat = f.get("yhat")
            yl = f.get("yhat_lower")
            yu = f.get("yhat_upper")
            pdf.table_row(
                [
                    (_safe(f.get("stock_code")), 40),
                    (_safe(f.get("ds")), 36),
                    (_num(yhat) if yhat is not None else "-", 36),
                    (_num(yl) if yl is not None else "-", 31),
                    (_num(yu) if yu is not None else "-", 31),
                ],
                shade=idx % 2 == 1,
            )
        pdf.ln(4)

    # D. Worker task checklists (full)
    if tasks:
        pdf.sub_title("D.  Full Worker Task Checklists")
        for task in tasks:
            priority = _safe(task.get("priority"), "medium").upper()
            title = _safe(task.get("title"))
            assigned = _safe(task.get("assigned_to") or "-")
            due = _safe(task.get("due_date") or "-")

            pdf.set_font("Helvetica", style="B", size=9)
            pdf.cell(0, 6, f"[{priority}]  {title}", ln=True)
            pdf.set_font("Helvetica", size=8)
            pdf.cell(0, 5, f"Owner: {assigned}   Due: {due}", ln=True)
            pdf.set_font("Helvetica", size=9)
            pdf.set_x(pdf.l_margin)
            pdf.multi_cell(pdf.epw, 5, _safe(task.get("description")))

            checklist = task.get("checklist", [])
            if checklist:
                pdf.set_font("Helvetica", style="I", size=8)
                pdf.cell(0, 5, "Checklist:", ln=True)
                pdf.set_font("Helvetica", size=8)
                for item in checklist:
                    mark = "[x]" if item.get("completed") else "[ ]"
                    pdf.set_x(pdf.l_margin + 8)
                    pdf.cell(0, 5, f"{mark}  {_safe(item.get('step'))}", ln=True)

            criteria = task.get("acceptance_criteria", [])
            if criteria:
                pdf.set_font("Helvetica", style="I", size=8)
                pdf.cell(0, 5, "Acceptance criteria:", ln=True)
                pdf.set_font("Helvetica", size=8)
                for c in criteria:
                    pdf.set_x(pdf.l_margin + 8)
                    pdf.multi_cell(pdf.epw - 8, 5, f"-  {_safe(c)}")

            pdf.ln(2)
            pdf.set_draw_color(210, 210, 210)
            y = pdf.get_y()
            pdf.line(pdf.l_margin, y, pdf.l_margin + pdf.epw, y)
            pdf.ln(3)

    # E. All audit findings
    all_findings = audit.get("findings", [])
    if all_findings:
        pdf.sub_title("E.  All Audit Findings")
        for f in all_findings:
            sev = _safe(f.get("severity"), "info")
            ftype = _safe(f.get("finding_type"))
            desc = _safe(f.get("description"))
            rec = f.get("recommendation")
            pdf.severity_label(sev)
            pdf.set_font("Helvetica", style="B", size=8)
            pdf.set_x(pdf.l_margin + 30)
            pdf.cell(0, 5, ftype, ln=True)
            pdf.set_font("Helvetica", size=8)
            pdf.set_x(pdf.l_margin + 30)
            pdf.multi_cell(pdf.epw - 30, 5, desc)
            if rec:
                pdf.set_font("Helvetica", style="I", size=8)
                pdf.set_x(pdf.l_margin + 30)
                pdf.multi_cell(pdf.epw - 30, 5, f"-> {_safe(rec)}")
            pdf.set_x(pdf.l_margin)
            pdf.ln(2)

    # F. SQL evidence
    queries = ar.get("queries_executed", [])
    if queries:
        pdf.sub_title("F.  SQL Queries Executed")
        for q in queries:
            sql = _safe(q.get("sql", ""))
            if sql and sql != "-":
                pdf.set_font("Courier", size=7)
                pdf.set_x(pdf.l_margin)
                pdf.multi_cell(pdf.epw, 4.5, sql)
                pdf.ln(2)


# ─── Public API ───────────────────────────────────────────────────────────────

def generate_report_pdf(artifacts: dict[str, Any], run_id: str) -> bytes:
    """Build an executive business-cycle PDF from run artifacts."""
    ar = artifacts.get("analyst_report", {})
    period_start = _safe(ar.get("period_start", ""))
    period_end = _safe(ar.get("period_end", ""))
    period = f"{period_start} to {period_end}" if period_start != "-" else run_id[:8]

    pdf = _PDF(run_id=run_id, period=period)

    decision = artifacts.get("decision", {})
    forecast = artifacts.get("forecast_report", {})
    audit = artifacts.get("audit_report", {})
    worker_tasks = artifacts.get("worker_tasks", [])
    if not isinstance(worker_tasks, list):
        worker_tasks = []

    _page_cover(pdf, artifacts, run_id, period)
    _page_exec_summary(pdf, ar, decision, audit)
    _page_business_context(pdf, ar, decision)
    _page_performance_snapshot(pdf, ar)
    _page_key_insights(pdf, ar)
    _page_forecast(pdf, forecast)
    _page_action_plan(pdf, decision, worker_tasks)
    _page_risks(pdf, decision, audit)
    _page_appendix(pdf, ar, forecast, worker_tasks, audit)

    return bytes(pdf.output())
