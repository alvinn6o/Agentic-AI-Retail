# Agentic Retail Ops Simulator

A portfolio project that automates a retail operations workflow using a pipeline of specialised AI agents. Agents collaborate to ingest data, analyse sales performance, forecast demand, make operational decisions, generate worker tasks, and audit their own outputs — grounded in real transaction data with a full evidence trail.

---

## Overview

The simulator replaces a manual weekly ops cycle (analyst → demand planner → ops manager → coordinator) with an autonomous agent pipeline that runs the same process in under two minutes.

**Two modes:**
- **Bounded** — agents can only query data up to a chosen `as_of` date, simulating real-world conditions
- **Omniscient** — agents have access to the full dataset, providing a "best possible" benchmark to compare against bounded decisions

---

## Agent Architecture

Six agents, each with a single responsibility, communicating only through a shared `WorkflowState`:

| Agent | Responsibility |
|---|---|
| **DataEngineerAgent** | Ingests and validates raw CSV data into DuckDB. Fully deterministic — no LLM. |
| **AnalystAgent** | Computes KPIs (revenue, orders, return rate, top/bottom SKUs) via SQL. LLM writes narrative and anomaly detection only — all numbers come from query evidence. |
| **DataScientistAgent** | Per-SKU demand forecasting using LightGBM (lag + calendar features) or seasonal naive fallback. Real 28-day holdout backtest. No LLM. |
| **ManagerAgent** | Generates 3–7 business actions (restock, markdown, promo, etc.) from KPI + forecast inputs. Forecast reliability is gated on MAPE threshold before the LLM sees it. |
| **WorkerAgent** | Translates manager decisions into executable task cards with checklists and acceptance criteria, routed to the appropriate team. |
| **AuditorAgent** | Cross-checks all agent outputs for factuality, grounding, and SOP policy compliance. Flags mismatches with severity levels and remediation recommendations. |

---

## Workflow

```
data_engineer
     │
  ┌──┴──┐
analyst  data_scientist   ← parallel
  └──┬──┘
   fan_in
     │
  manager
     │
  worker
     │
 auditor
     │
 persist → END
```

Conditional edges act as circuit breakers: if an upstream artifact is missing, the pipeline skips downstream nodes and routes directly to `persist`, guaranteeing partial results are always saved.

---

## Pipelines

### Data Ingestion & Validation

Raw CSV (541,909 rows, latin-1 encoded) is processed by `DataEngineerAgent` into a curated analytical warehouse:

```
raw CSV
  → pandas: normalize columns, cast types, derive revenue = quantity × unit_price
  → ValidatorTool: schema checks, null audit, duplicate detection, negative price flagging
  → write to fact_sales.parquet (columnar, compressed)
  → load into DuckDB fact_sales table
```

Negative-quantity rows (returns) are retained and used in the return rate KPI.

### Demand Forecasting

`DataScientistAgent` forecasts 28-day demand for the top 5 SKUs by revenue. No LLM involved — fully deterministic and numerically evaluated.

**Model selection:**

| Condition | Model |
|---|---|
| Series ≥ 56 days AND ≥ 14 non-zero demand days | LightGBM |
| Otherwise | Improved Seasonal Naive |

**LightGBM pipeline:**
- Features: `day_of_week`, `week_of_year`, `month`, `lag_7`, `lag_14`, `lag_28`, `rolling_mean_7`, `rolling_mean_14`, `rolling_std_7`
- Train/test split: all-but-last-28 days for training, last 28 days as a real holdout
- Backtest: MAPE and RMSE computed on held-out window (not in-sample)
- Forecast: recursive multi-step — each day's prediction is fed back as a lag for the next
- Uncertainty: ±1.28 × training residual std (≈ 80% prediction interval)

**Seasonal Naive fallback:**
- Weighted average of the last 4 same-day-of-week values (weights: 2, 2, 1, 1)
- Uncertainty: ±1.5 × same-DOW std

### Hallucination Prevention

All KPI values are computed by SQL queries before any LLM call. Each query is captured as a `QueryEvidence` object (SQL text + result). The LLM receives the pre-computed numbers and is only permitted to fill `narrative` and `anomalies` fields — it cannot generate or alter numeric values.

Bounded mode date enforcement happens at the `SQLTool` layer, not the prompt layer:

```python
# Injected programmatically before every query — the LLM cannot bypass this
if mode == "bounded":
    sql = sql.replace("FROM fact_sales", f"FROM fact_sales WHERE invoice_date <= '{as_of_date}'")
```

### LLM Output Validation & Repair

When an LLM response fails Pydantic schema validation (malformed JSON, missing fields, wrong types), the base agent retries with a structured correction prompt — up to 3 attempts:

```
Attempt 1: initial response → ValidationError
Attempt 2: "Your previous response failed with: {error}. Fix it." → ValidationError
Attempt 3: "Return ONLY valid JSON matching this schema: {schema}" → success or give up
```

### Audit Pipeline

`AuditorAgent` runs deterministic checks first, then an LLM factuality pass:

1. Every KPI has a `QueryEvidence` entry
2. In bounded mode: `period_end` ≤ `as_of_date` (no future data leakage)
3. Decision actions and rationale are non-empty; confidence is a valid float 0–1
4. LLM cross-checks every narrative number against its SQL evidence, flags hallucinated metrics, and checks SOP policy adherence via RAG-retrieved policy documents

Findings carry severity (`info` / `warning` / `error`), affected field, reported vs. verified value, and a remediation recommendation.

### Product Taxonomy (Optional)

Clusters ~4,000 raw product descriptions into human-readable categories:

```
raw descriptions
  → regex cleaning (strip colours, pack sizes)
  → embed with SentenceTransformer (all-MiniLM-L6-v2, 384-dim)
  → K-means clustering (k=30, normalized)
  → Claude labels each cluster → category name (e.g. "Seasonal Decorations")
  → persist to dim_product with taxonomy_version tag
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Orchestration** | LangGraph (`StateGraph`) — directed graph with fan-out/fan-in parallelism and conditional routing |
| **LLM** | LangChain + `langchain-anthropic` — provider-agnostic; supports Anthropic, OpenAI, Ollama |
| **Data warehouse** | DuckDB — embedded OLAP engine queried directly over Parquet |
| **Storage format** | Apache Parquet — columnar storage for the cleaned 541,909-row transaction dataset |
| **Forecasting** | LightGBM with lag (7/14/28-day), calendar, and rolling-window features; seasonal naive fallback |
| **Embeddings** | `sentence-transformers` (`all-MiniLM-L6-v2`) — used for RAG tool and product taxonomy clustering |
| **Product taxonomy** | scikit-learn K-means on sentence embeddings, cluster labels generated by Claude |
| **Schema validation** | Pydantic v2 — typed contracts at every agent handoff; repair loop on validation failure |
| **Backend** | FastAPI + Uvicorn — async REST API with background task execution and auto-generated Swagger docs |
| **Frontend** | Streamlit — run dashboard with Plotly charts, run-history selector, and PDF export |
| **PDF export** | fpdf2 — pure-Python report generation |
| **Logging** | structlog — structured JSON logs with `run_id` on every event; optional LangSmith tracing |
| **Data processing** | pandas — ingest/cleaning stage; DuckDB handles all analytical queries |
| **Infrastructure** | Docker Compose (optional Postgres + pgvector) |

---

## Project Structure

```
agent_project/
├── backend/app/
│   ├── agents/          # Agent class definitions + YAML prompts
│   ├── api/             # FastAPI route handlers
│   ├── core/            # Config (Pydantic Settings), DuckDB init, logging
│   ├── graph/           # LangGraph StateGraph + WorkflowState
│   ├── models/          # Pydantic schemas (reports, decisions, audit)
│   └── tools/           # SQL, validator, Python, and RAG tools
├── data/
│   ├── raw/             # Source: UCI Online Retail dataset (541,909 rows)
│   ├── curated/         # fact_sales.parquet + warehouse.duckdb (auto-generated)
│   └── docs/            # SOP policy documents (restock, markdown)
├── evals/               # Forecast accuracy and factuality evaluation harnesses
├── scripts/             # ingest.py, build_taxonomy.py, run_cycle.py
├── ui/                  # Streamlit app + components + PDF export
├── infra/               # docker-compose.yml
└── start.sh             # One-command startup
```

---

## How to Run

**Prerequisites:** Python 3.11+, an API key (Anthropic / OpenAI / Ollama), and on macOS: `brew install libomp` for LightGBM.

```bash
# 1. Clone and enter the project
git clone <https://github.com/alvinn6o/Agentic-AI-Retail.git>
cd agent_project

# 2. Create virtual environment
python3 -m venv .venv && source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env — set LLM_PROVIDER and your API key

# 5. Add source data
# Download UCI Online Retail dataset → place at data/raw/data.csv

# 6. Start everything
bash start.sh
```

| Service | URL |
|---|---|
| Streamlit UI | http://localhost:8501 |
| FastAPI backend | http://localhost:8000 |
| Swagger docs | http://localhost:8000/docs |

**Run individually:**

```bash
uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
streamlit run ui/streamlit_app.py --server.port 8501
```

**Run a cycle from the CLI:**

```bash
python scripts/run_cycle.py --as_of 2011-06-30 --mode bounded
python scripts/run_cycle.py --as_of 2011-06-30 --mode omniscient
```

**Run tests:**

```bash
pytest
pytest --cov=backend --cov-report=term-missing
```

---

## API Reference

### `POST /api/v1/run`
Trigger a new agent workflow cycle (runs asynchronously).

```json
{ "as_of_date": "2011-06-30", "start_date": "2011-04-01", "mode": "bounded" }
```

### `GET /api/v1/run/{run_id}/status`
Poll run status: `running` | `completed` | `failed`

### `GET /api/v1/run/{run_id}/artifacts`
Retrieve all persisted artifacts (analyst report, forecast, decision, audit, worker tasks).

### `GET /api/v1/runs`
List recent runs. Query param: `limit` (default: 20).

---

## Configuration

Key `.env` variables:

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `anthropic` | `anthropic` \| `openai` \| `ollama` |
| `ANTHROPIC_API_KEY` | — | Anthropic API key |
| `OPENAI_API_KEY` | — | OpenAI API key |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_MODEL` | `llama3.2` | Ollama model name |
| `DEFAULT_MODEL_ANTHROPIC` | `claude-haiku-4-5-20251001` | Claude model ID |
| `DEFAULT_MODEL_OPENAI` | `gpt-4o-mini` | OpenAI model ID |
| `DUCKDB_PATH` | `data/curated/warehouse.duckdb` | DuckDB warehouse path |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | SentenceTransformer model |
| `MAX_REPAIR_RETRIES` | `3` | Max LLM repair attempts on schema validation failure |
| `LANGCHAIN_TRACING_V2` | — | Set `true` to enable LangSmith tracing |

---

## License

MIT
