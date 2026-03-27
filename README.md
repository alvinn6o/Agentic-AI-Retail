# Agentic Retail Ops Control Simulator

A portfolio project that automates a retail operations workflow with specialised AI agents plus deterministic control gates. The system ingests transaction data, computes grounded KPIs, forecasts demand, proposes actions, reviews those actions against explicit control rules, generates executable tasks, audits the outputs, and prepares approved tasks for enterprise handoff.

The dataset is still retail. The regulated-domain value comes from the workflow design: bounded data access, typed contracts, approval gating, audit checks, and controlled API dispatch.

For a direct strengths/weaknesses review and interview narrative, see `docs/PROJECT_ASSESSMENT.md`.

---

## Overview

The simulator replaces a manual weekly ops cycle with an autonomous pipeline that runs in under two minutes.

**Data modes**
- `bounded`: agents can only query data up to a chosen `as_of_date`
- `omniscient`: agents can access the full dataset for benchmark comparisons

**Control profiles**
- `standard`: retail experimentation with lighter release controls
- `regulated`: stricter approval holds, blocked non-standard actions, and dispatch gating

---

## Workflow

```text
data_engineer
     |
  +--+--+
analyst  data_scientist
  +--+--+
     |
   fan_in
     |
  manager
     |
control_review
   +-+------+
worker    auditor
   +---+----+
      |
   dispatch
      |
   persist
```

Key orchestration behaviors:

- `analyst` and `data_scientist` run in parallel
- downstream circuit breakers skip to `persist` if required artifacts are missing
- `control_review` decides whether actions can auto-release, must wait for approval, or are blocked
- `dispatch` only prepares or sends tasks after the audit passes

---

## Architecture

| Component | Responsibility |
|---|---|
| `DataEngineerAgent` | Deterministic ingest and schema validation into DuckDB |
| `AnalystAgent` | SQL-grounded KPI generation; LLM only writes narrative/anomalies |
| `DataScientistAgent` | Deterministic demand forecasting with backtest metrics |
| `ManagerAgent` | LLM decision drafting from analyst and forecast artifacts |
| `ControlReviewService` | Deterministic risk-tiering, approval roles, and release gating |
| `WorkerAgent` | Converts releasable actions into executable task cards |
| `AuditorAgent` | Deterministic checks plus LLM-assisted factuality and policy review |
| `EnterpriseDispatchService` | Dry-run or live enterprise API handoff for approved tasks |

---

## Guardrails

### Grounded analytics

- KPI values come from SQL before any LLM call
- each numeric claim can carry `QueryEvidence`
- bounded-mode date enforcement happens in the SQL tool, not in prompts

### Structured outputs

- Pydantic models validate every major handoff
- malformed LLM JSON is retried with repair prompts

### Deterministic controls

- manager actions are reviewed outside the LLM
- every action gets a risk tier, approval role, and execution state
- only `auto_release` actions reach the worker stage
- the `regulated` profile blocks untargeted or non-standard actions and escalates larger changes

### Audit and release

- the auditor checks grounding, bounded-mode leakage, and decision completeness
- enterprise dispatch is blocked if the audit contains error findings
- dispatch runs in dry-run mode by default, producing an inspectable outbox artifact

---

## Tech Stack

| Layer | Technology |
|---|---|
| Orchestration | LangGraph |
| LLM orchestration | LangChain |
| Backend API | FastAPI + Uvicorn |
| Warehouse | DuckDB |
| Data processing | pandas + PyArrow |
| Forecasting | LightGBM or seasonal naive fallback |
| Embeddings / RAG | sentence-transformers |
| Validation | Pydantic v2 |
| UI | Streamlit |
| Logging | structlog |
| Export | HTTP API adapter with dry-run support |

---

## Project Structure

```text
agent_project/
├── backend/app/
│   ├── agents/      # LLM and deterministic agent implementations
│   ├── api/         # FastAPI routes
│   ├── core/        # config, logging, database
│   ├── graph/       # LangGraph workflow
│   ├── models/      # typed artifacts
│   ├── services/    # control review + enterprise dispatch
│   └── tools/       # SQL, validation, Python, RAG
├── data/
│   ├── raw/         # source CSV
│   ├── curated/     # generated warehouse artifacts
│   └── docs/        # SOPs and change-control policies
├── docs/            # project assessment and portfolio framing
├── evals/           # eval harnesses
├── scripts/         # CLI utilities
└── ui/              # Streamlit app
```

---

## How To Run

Prerequisites:

- Python 3.11+
- one LLM provider configured
- on macOS, `brew install libomp` for LightGBM

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Add the UCI Online Retail CSV to `data/raw/data.csv`.

Start the stack:

```bash
bash start.sh
```

Run services individually:

```bash
uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
streamlit run ui/streamlit_app.py --server.port 8501
```

Run from CLI:

```bash
python3 scripts/run_cycle.py --as_of 2011-06-30 --mode bounded
python3 scripts/run_cycle.py --as_of 2011-06-30 --mode bounded --control_profile regulated
```

Run tests:

```bash
pytest
```

---

## API

### `POST /api/v1/run`

```json
{
  "start_date": "2011-04-01",
  "as_of_date": "2011-06-30",
  "mode": "bounded",
  "control_profile": "regulated",
  "skip_ingest": true
}
```

### `GET /api/v1/run/{run_id}/status`

Returns `running`, `completed`, or `failed`.

### `GET /api/v1/run/{run_id}/artifacts`

Returns persisted artifacts including:

- `analyst_report`
- `forecast_report`
- `decision`
- `control_review`
- `worker_tasks`
- `audit_report`
- `dispatch_report`

### `GET /api/v1/runs`

Lists recent runs.

---

## Configuration

Important `.env` variables:

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `anthropic` | `anthropic`, `openai`, or `ollama` |
| `DUCKDB_PATH` | `data/curated/warehouse.duckdb` | Warehouse path |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Local embedding model |
| `MAX_REPAIR_RETRIES` | `3` | Structured-output repair retries |
| `ENTERPRISE_TARGET_SYSTEM` | `custom` | Outbound target label |
| `ENTERPRISE_API_BASE_URL` | — | Base URL for live dispatch |
| `ENTERPRISE_TASK_ENDPOINT` | `/tasks` | Relative task endpoint |
| `ENTERPRISE_DRY_RUN` | `true` | Prepare payloads without sending them |

---

## What This Demonstrates

- multi-step agentic orchestration
- parallel branches with fan-in
- deterministic guardrails around LLM outputs
- audit and release gating
- typed artifacts and persistent evidence trails
- API-oriented enterprise handoff patterns
