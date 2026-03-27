"""Shared enterprise-style UI helpers for the Streamlit app."""

from __future__ import annotations

from html import escape

import streamlit as st

_THEME_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

:root {
  --bg-top: #eef4f6;
  --bg-bottom: #f7f9fb;
  --surface: rgba(255, 255, 255, 0.94);
  --surface-strong: #ffffff;
  --surface-muted: #f4f7f9;
  --border: #d7e1e7;
  --border-strong: #bdd0db;
  --ink: #132534;
  --muted: #5e7183;
  --accent: #0d6b73;
  --accent-strong: #0a4d56;
  --accent-soft: #dff3f1;
  --success: #156f4f;
  --success-soft: #e7f7f0;
  --warning: #8a5a12;
  --warning-soft: #fff3df;
  --danger: #8f3042;
  --danger-soft: #fdecef;
  --shadow: 0 18px 45px rgba(17, 38, 56, 0.08);
}

html, body, [class*="css"] {
  font-family: "IBM Plex Sans", sans-serif;
}

.stApp {
  background:
    radial-gradient(circle at top left, rgba(13, 107, 115, 0.10), transparent 28%),
    radial-gradient(circle at top right, rgba(21, 111, 79, 0.08), transparent 22%),
    linear-gradient(180deg, var(--bg-top) 0%, var(--bg-bottom) 38%, #f8fafb 100%);
  color: var(--ink);
}

p, li, label, .stMarkdown, .stCaption, .stText {
  color: var(--ink);
}

a {
  color: var(--accent-strong);
}

.block-container {
  max-width: 1380px;
  padding-top: 1.5rem;
  padding-bottom: 3rem;
}

[data-testid="stSidebar"] {
  background:
    linear-gradient(180deg, rgba(255,255,255,0.98) 0%, rgba(246,249,251,0.98) 100%);
  border-right: 1px solid var(--border);
}

[data-testid="stSidebar"] .block-container {
  padding-top: 1.25rem;
}

[data-testid="stSidebar"] label,
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span,
[data-testid="stSidebar"] div {
  color: var(--ink);
}

[data-testid="stMetric"] {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 18px;
  padding: 0.8rem 1rem;
  box-shadow: var(--shadow);
}

[data-testid="stMetricLabel"] {
  color: var(--muted);
  font-size: 0.78rem;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

[data-testid="stMetricValue"] {
  color: var(--ink);
  font-size: 1.5rem;
}

div.stButton > button,
div.stDownloadButton > button {
  border-radius: 14px;
  border: 1px solid transparent;
  background: linear-gradient(135deg, var(--accent) 0%, var(--accent-strong) 100%);
  color: white;
  font-weight: 600;
  min-height: 2.8rem;
  box-shadow: 0 12px 30px rgba(10, 77, 86, 0.22);
}

div.stButton > button:hover,
div.stDownloadButton > button:hover {
  border-color: rgba(255, 255, 255, 0.12);
  transform: translateY(-1px);
}

[data-baseweb="tab-list"] {
  gap: 0.35rem;
  background: rgba(255,255,255,0.6);
  border: 1px solid var(--border);
  border-radius: 18px;
  padding: 0.35rem;
}

[data-baseweb="tab"] {
  border-radius: 14px;
  color: var(--muted);
  font-weight: 600;
  padding: 0.55rem 0.95rem;
}

[data-baseweb="tab"][aria-selected="true"] {
  background: linear-gradient(135deg, #14334a 0%, #0f5963 100%);
  color: white;
}

div[data-testid="stExpander"] {
  border: 1px solid var(--border);
  border-radius: 18px;
  background: rgba(255,255,255,0.84);
  box-shadow: var(--shadow);
}

div[data-testid="stExpander"] summary,
div[data-testid="stExpander"] summary span,
div[data-testid="stExpander"] label,
div[data-testid="stExpander"] p,
div[data-testid="stExpander"] div {
  color: var(--ink);
}

div[data-testid="stDataFrame"] {
  border: 1px solid var(--border);
  border-radius: 18px;
  background: rgba(255,255,255,0.9);
  box-shadow: var(--shadow);
}

.enterprise-hero {
  background:
    radial-gradient(circle at top right, rgba(115, 226, 200, 0.22), transparent 28%),
    linear-gradient(135deg, #0f2233 0%, #153a4f 50%, #19585f 100%);
  border: 1px solid rgba(201, 231, 236, 0.24);
  color: white;
  border-radius: 28px;
  padding: 1.5rem 1.7rem 1.45rem;
  box-shadow: 0 24px 55px rgba(10, 28, 43, 0.18);
  margin-bottom: 1rem;
}

.hero-eyebrow,
.section-eyebrow,
.sidebar-eyebrow {
  font-family: "IBM Plex Mono", monospace;
  font-size: 0.76rem;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  opacity: 0.88;
}

.hero-title {
  font-size: 2.15rem;
  font-weight: 700;
  letter-spacing: -0.03em;
  margin: 0.25rem 0 0.5rem;
}

.hero-subtitle {
  max-width: 62rem;
  color: rgba(236, 245, 247, 0.92);
  font-size: 1rem;
  line-height: 1.6;
  margin-bottom: 1rem;
}

.pill-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
}

.status-pill {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 0.32rem 0.72rem;
  border: 1px solid transparent;
  font-family: "IBM Plex Mono", monospace;
  font-size: 0.73rem;
  letter-spacing: 0.04em;
}

.status-pill--neutral {
  background: rgba(243, 247, 249, 0.82);
  color: #244255;
  border-color: rgba(202, 218, 227, 0.8);
}

.status-pill--info {
  background: rgba(220, 242, 245, 0.92);
  color: #0a4d56;
  border-color: rgba(139, 197, 203, 0.95);
}

.status-pill--success {
  background: rgba(226, 247, 238, 0.96);
  color: var(--success);
  border-color: rgba(164, 219, 194, 0.95);
}

.status-pill--warning {
  background: rgba(255, 244, 224, 0.96);
  color: var(--warning);
  border-color: rgba(239, 210, 160, 0.95);
}

.status-pill--danger {
  background: rgba(253, 234, 239, 0.96);
  color: var(--danger);
  border-color: rgba(236, 181, 195, 0.95);
}

.surface-card,
.summary-card,
.detail-card,
.sidebar-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 22px;
  box-shadow: var(--shadow);
}

.summary-card {
  padding: 1rem 1.1rem;
  min-height: 142px;
}

.summary-label {
  font-family: "IBM Plex Mono", monospace;
  color: var(--muted);
  font-size: 0.75rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.summary-value {
  font-size: 1.95rem;
  font-weight: 700;
  letter-spacing: -0.04em;
  color: var(--ink);
  margin: 0.5rem 0 0.35rem;
}

.summary-detail {
  color: var(--muted);
  font-size: 0.92rem;
  line-height: 1.45;
}

.section-heading {
  margin: 0.3rem 0 1rem;
}

.section-title {
  font-size: 1.4rem;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--ink);
  margin: 0.25rem 0 0.2rem;
}

.section-body {
  color: var(--muted);
  line-height: 1.55;
  max-width: 56rem;
}

.detail-card {
  padding: 1rem 1.1rem;
  margin-bottom: 0.85rem;
}

.detail-title {
  font-size: 1rem;
  font-weight: 700;
  color: var(--ink);
  margin-bottom: 0.35rem;
}

.detail-meta {
  color: var(--muted);
  font-size: 0.88rem;
  line-height: 1.5;
}

.detail-body {
  color: var(--ink);
  font-size: 0.95rem;
  line-height: 1.6;
  margin-top: 0.55rem;
}

.detail-body ul {
  margin: 0.4rem 0 0.1rem 1rem;
  padding: 0;
}

.summary-card *,
.detail-card *,
.sidebar-card * {
  color: inherit;
}

.summary-card strong,
.detail-card strong,
.sidebar-card strong {
  color: var(--ink);
}

.sidebar-card {
  padding: 1rem 1rem 0.95rem;
  margin-bottom: 0.85rem;
  background: linear-gradient(180deg, rgba(255,255,255,0.96) 0%, rgba(244,247,249,0.98) 100%);
}

.sidebar-title {
  font-weight: 700;
  font-size: 1.1rem;
  color: var(--ink);
  margin: 0.3rem 0;
}

.sidebar-copy {
  color: var(--muted);
  line-height: 1.55;
  font-size: 0.92rem;
}
</style>
"""


def inject_enterprise_theme() -> None:
    st.markdown(_THEME_CSS, unsafe_allow_html=True)


def status_pill_html(label: str, tone: str = "neutral") -> str:
    safe_label = escape(label)
    safe_tone = escape(tone)
    return f'<span class="status-pill status-pill--{safe_tone}">{safe_label}</span>'


def render_hero(title: str, subtitle: str, pills: list[str] | None = None) -> None:
    pills_html = ""
    if pills:
        pills_html = f'<div class="pill-row">{"".join(pills)}</div>'
    st.markdown(
        (
            '<section class="enterprise-hero">'
            '<div class="hero-eyebrow">Operations Control Board</div>'
            f'<div class="hero-title">{escape(title)}</div>'
            f'<div class="hero-subtitle">{escape(subtitle)}</div>'
            f"{pills_html}"
            "</section>"
        ),
        unsafe_allow_html=True,
    )


def render_section_heading(title: str, description: str, eyebrow: str = "Control Surface") -> None:
    st.markdown(
        (
            '<div class="section-heading">'
            f'<div class="section-eyebrow">{escape(eyebrow)}</div>'
            f'<div class="section-title">{escape(title)}</div>'
            f'<div class="section-body">{escape(description)}</div>'
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def render_summary_card(label: str, value: str, detail: str = "") -> None:
    detail_html = f'<div class="summary-detail">{escape(detail)}</div>' if detail else ""
    st.markdown(
        (
            '<div class="summary-card">'
            f'<div class="summary-label">{escape(label)}</div>'
            f'<div class="summary-value">{escape(value)}</div>'
            f"{detail_html}"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def render_detail_card(title: str, body: str, meta: str = "", pills: list[str] | None = None) -> None:
    meta_html = f'<div class="detail-meta">{meta}</div>' if meta else ""
    pills_html = f'<div class="pill-row">{"".join(pills or [])}</div>' if pills else ""
    st.markdown(
        (
            '<div class="detail-card">'
            f'<div class="detail-title">{escape(title)}</div>'
            f"{meta_html}"
            f"{pills_html}"
            f'<div class="detail-body">{body}</div>'
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def render_sidebar_intro(title: str, body: str) -> None:
    st.markdown(
        (
            '<div class="sidebar-card">'
            '<div class="sidebar-eyebrow">Enterprise Workspace</div>'
            f'<div class="sidebar-title">{escape(title)}</div>'
            f'<div class="sidebar-copy">{escape(body)}</div>'
            "</div>"
        ),
        unsafe_allow_html=True,
    )
