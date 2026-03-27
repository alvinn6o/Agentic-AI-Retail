# Project Assessment

## Purpose

This document captures the current strengths and weaknesses of the project, the changes implemented in this iteration, and how to frame it as a prior example of multi-step agentic workflow automation with guardrails and enterprise integration.

Important constraint: the underlying data is still retail transaction data. The project should be presented honestly as a retail workflow simulator that has been extended with deterministic controls commonly required in regulated or safety-critical environments.

## Baseline Strengths

- The architecture already had clear multi-step orchestration with a real graph, parallel fan-out/fan-in, and circuit breakers.
- The strongest guardrail was already in place: KPI numbers come from deterministic SQL, not the LLM.
- Typed Pydantic contracts existed at every handoff, which is exactly the kind of structured boundary interviewers expect to see in agentic systems.
- The workflow persisted artifacts end to end, which made it inspectable and testable rather than a black-box demo.
- The repo already included evaluation harnesses for factuality, forecasting quality, and decision quality.
- The UI and API were good enough to demonstrate the pipeline interactively.

## Baseline Weaknesses

- The project described policy compliance, but it did not have a deterministic approval gate between model output and operational execution.
- Worker tasks could be generated directly from manager decisions without a separate release-control layer.
- There was no concrete enterprise handoff artifact or API adapter, so "integration with enterprise systems" was more implicit than demonstrated.
- The regulated-domain story was weak because the code was framed purely as retail optimization even though the control patterns were transferable.
- The run context did not carry an explicit control profile, so there was no first-class way to tighten workflow behavior for higher-risk settings.
- A couple of Pydantic and datetime patterns were still using deprecated forms.

## Implemented Changes

### 1. Deterministic control review

Added `ControlReviewService` and new typed artifacts in:

- `backend/app/services/control_review.py`
- `backend/app/models/controls.py`

What it does:

- reviews every manager action after the LLM step
- assigns a control family, risk tier, approval role, and execution state
- supports two profiles: `standard` and `regulated`
- allows only `auto_release` actions to continue into worker task generation
- holds or blocks riskier actions before execution

Key regulated-profile behaviors:

- untargeted actions are blocked
- customer-facing pricing actions require approval
- larger inventory changes escalate to operations manager or director review
- non-standard actions are blocked until a human defines the procedure

### 2. Enterprise dispatch outbox / adapter

Added `EnterpriseDispatchService` and new typed artifacts in:

- `backend/app/services/enterprise_dispatch.py`
- `backend/app/models/integration.py`

What it does:

- prepares outbound task payloads for enterprise systems
- runs in dry-run mode by default
- can POST to a configured API endpoint when enabled
- blocks release if the audit fails
- returns an explicit dispatch artifact that can be shown in the UI or API

This materially improves the project as an interview example because it now demonstrates a full chain:

`LLM recommendation -> deterministic control gate -> task generation -> audit gate -> enterprise handoff`

### 3. Workflow orchestration update

Updated:

- `backend/app/graph/workflow.py`
- `backend/app/graph/state.py`

The graph now runs:

1. `data_engineer`
2. `analyst` and `data_scientist` in parallel
3. `manager`
4. `control_review`
5. `worker` only for auto-released actions
6. `auditor`
7. `dispatch`
8. `persist`

This is the most important improvement for the "multi-step agentic workflow automation" narrative because the orchestration now contains explicit release controls rather than just analysis and tasking.

### 4. Control profile in API, CLI, and UI

Added `control_profile` to:

- `backend/app/models/run_context.py`
- `backend/app/api/routes.py`
- `scripts/run_cycle.py`
- `ui/streamlit_app.py`

The UI now exposes a `Regulated` mode so the workflow can be demonstrated live without code changes.

### 5. New policy document

Added `data/docs/sop_agent_change_control.md`.

This gives the control review and demo narrative a concrete SOP-backed policy source instead of vague claims about approval logic.

### 6. Verification

Added `backend/tests/test_controls.py`.

New tests cover:

- auto-release for low-risk inventory changes
- blocking untargeted regulated actions
- approval holds for larger regulated inventory changes
- dispatch blocking when audit fails
- dry-run enterprise dispatch behavior

## How To Discuss This Project

A concise interview framing:

"I built a LangGraph-based multi-agent workflow that automates a weekly operating cycle end to end. The system ingests data, computes grounded KPIs, runs deterministic forecasting, asks an LLM manager to propose actions, then passes those actions through a deterministic control-review layer before any task is generated or exported. Only low-risk actions can auto-release. Higher-risk or non-standard actions are held for approval or blocked. After that, an auditor checks factuality and policy alignment, and only then does the workflow prepare enterprise payloads for downstream systems. I used typed schemas, bounded-data enforcement, retry-and-repair on LLM outputs, persistent artifacts, and tests for both guardrails and evaluation."

Why this works well:

- It demonstrates orchestration, not just prompting.
- It shows a separation between model judgment and deterministic release logic.
- It includes concrete API integration behavior, even when running in dry-run mode.
- It is honest about the dataset while still showing design patterns relevant to regulated domains.

## Best Talking Points For Regulated / Safety-Critical Interest

- The LLM is intentionally not trusted with the final release decision.
- The most sensitive control points are deterministic and inspectable.
- Every stage produces typed, persisted artifacts that can be reviewed later.
- There is a clear distinction between recommendation, approval, execution, and dispatch.
- The `regulated` profile shows how the same workflow can tighten thresholds without rewriting the whole system.

## Remaining Gaps

- The project still uses retail data, so it is best framed as a controlled simulation rather than a domain-authentic healthcare, finance, or industrial deployment.
- Approval holds are represented as artifacts and statuses; there is not yet a full human approval inbox or sign-off UI.
- Enterprise dispatch is generic HTTP rather than a deep native integration with SAP, ServiceNow, Epic, or another real system.
- Policy logic is deterministic and transparent, but still heuristic rather than driven by a full policy engine or formal rule DSL.
- The UI PDF export has not been expanded to include the new control-review and dispatch artifacts yet.

## Recommended Next Steps

- Add a human approval endpoint and approval state transitions.
- Persist approval decisions separately from task generation.
- Add a stricter audit that cross-checks control-review outcomes against policy citations.
- Create one domain-specific profile, such as pharmacy inventory, medical device replenishment, or QA deviation handling, while keeping the current retail dataset clearly labeled as a simulator.
- Replace the generic enterprise adapter with one concrete system integration and a contract test suite.
