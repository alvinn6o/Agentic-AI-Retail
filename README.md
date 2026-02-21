# Agentic Retail Ops Simulator

A portfolio project that simulates a retail operations team using a pipeline of specialised AI agents. Agents collaborate to ingest data, analyse sales performance, forecast demand, make operational decisions, generate executable worker tasks, and audit their own outputs — all grounded in real transaction data with a complete evidence trail.

---

## Table of Contents

1. [The Imaginary Business](#1-the-imaginary-business)
2. [Data Pipeline](#2-data-pipeline)
3. [Agent Architecture](#3-agent-architecture)
4. [Workflow Orchestration](#4-workflow-orchestration)
5. [Technology Stack & Design Decisions](#5-technology-stack--design-decisions)
6. [Core Learning Objectives](#6-core-learning-objectives)
7. [Project Structure](#7-project-structure)
8. [How to Run](#8-how-to-run)
9. [API Reference](#9-api-reference)
10. [Configuration Reference](#10-configuration-reference)

---

## 1. The Imaginary Business

### Company: RetailCo

**RetailCo** is a mid-sized UK-based e-commerce retailer selling gift and homeware products to consumers across Europe. It operates from a single fulfilment warehouse and manages roughly 4,000 active SKUs across categories such as home décor, kitchenware, seasonal gifts, and stationery.

The business processes approximately 20,000–25,000 invoices per year with annual revenue around £8–10M. Orders span individual consumers through to small wholesale buyers (schools, gift shops) — reflected in the wide variance in order quantities.

### The Problem

RetailCo's ops cycle has historically been manual and slow:

| Role | Task | Tool |
|---|---|---|
| Data Analyst | Pull weekly sales report, compute KPIs | Excel pivot tables |
| Demand Planner | Forecast next 4–8 weeks per SKU | Excel with seasonal adjustments |
| Ops Manager | Review analyst + planner outputs, decide on restock/markdown actions | Weekly meeting |
| Store Coordinator | Receive decisions, create task lists for warehouse and marketing teams | Email |

This took roughly **3–5 working days** per weekly cycle, introduced transcription errors at every handoff, and produced decisions that were difficult to audit or reproduce.

### The Business Goals

This simulator replaces the four-role manual cycle with an autonomous agent pipeline that runs the same weekly process in under two minutes:

| Goal | How the simulator addresses it |
|---|---|
| Reduce cycle time from days to minutes | Fully automated ingest → analyse → forecast → decide → task → audit pipeline |
| Eliminate transcription errors between roles | Structured Pydantic schemas enforce typed contracts at every agent handoff |
| Ground every decision in verified data | All KPIs trace to SQL query evidence; no narrative numbers are LLM-generated |
| Make decisions reproducible and auditable | Every run persists all artifacts, queries, and decisions under a `run_id` |
| Compare decision quality across information horizons | Bounded mode (as-of cutoff) vs omniscient mode (full data) for apples-to-apples comparison |
| Enforce SOP compliance automatically | RAG tool retrieves restock and markdown policies; auditor checks policy adherence |

### The Optimisation Target

The business objective the agents implicitly optimise for is a **profit proxy**:

```
profit_proxy = revenue − stockout_penalty − overstock_waste_penalty
```

Agents are not given this formula explicitly. Instead, they receive grounded sales data, demand forecasts, and SOPs, and are expected to derive actions (restock, markdown, promotion, etc.) that move this proxy in the right direction.

### The Two Modes

A key feature of the project is the ability to compare agent decisions across two information regimes:

- **Bounded mode** — Agents can only query data up to a chosen `as_of` date. This simulates the realistic situation: at the time of the weekly cycle, the future hasn't happened yet. Use this to evaluate the quality of decisions made with realistic information.

- **Omniscient mode** — Agents have access to the full dataset including future dates. Use this to benchmark what the "best possible" decision with perfect information would look like, then compare it against bounded decisions.

The `as_of` date is user-configurable in the UI (any date within the dataset range: 2010-12-01 → 2011-12-09).

---

## 2. Data Pipeline

The pipeline transforms raw invoice CSV data into a curated analytical warehouse with three distinct stages.

### Source Data

The project uses the [UCI Online Retail dataset](https://archive.ics.uci.edu/dataset/352/online+retail): ~541,909 transactions from a UK retailer, 2010–2011.

**Raw schema** (`data/raw/data.csv`):

| Column | Type | Description |
|---|---|---|
| `InvoiceNo` | string | Invoice identifier (prefix C = cancellation/return) |
| `StockCode` | string | Product SKU |
| `Description` | string | Free-text product name |
| `Quantity` | integer | Units sold (negative = return) |
| `InvoiceDate` | string | Transaction timestamp |
| `UnitPrice` | float | Price per unit in GBP |
| `CustomerID` | float | Customer identifier (nullable) |
| `Country` | string | Customer country |

### Stage 1 — Ingest & Clean (`scripts/ingest.py`)

Orchestrated by `DataEngineerAgent`, this stage runs once (or on demand with `--reingest`):

```
raw CSV
  ↓ load with pandas (latin-1 encoding)
  ↓ normalize column names to snake_case
  ↓ cast types: invoice_date → datetime, quantity/unit_price → numeric
  ↓ derive revenue = quantity × unit_price
  ↓ ValidatorTool — schema checks, null audit, duplicate detection
  ↓ write to data/curated/fact_sales.parquet
  ↓ load into DuckDB → fact_sales table (541,909 rows)
```

**ValidatorTool checks:**
- All expected columns present
- Null counts per column (flagged if > threshold)
- Negative `unit_price` rows (data quality issue)
- Duplicate `(invoice_no, stock_code)` combinations
- Negative `quantity` rows are retained (they represent returns — used by return rate KPI)

### Stage 2 — Analytical Warehouse (`backend/app/core/database.py`)

DuckDB is initialised with the following schema on first startup:

```sql
-- Core transaction fact table
CREATE TABLE IF NOT EXISTS fact_sales (
    invoice_no    VARCHAR,
    invoice_date  TIMESTAMP,
    stock_code    VARCHAR,
    description   VARCHAR,
    quantity      INTEGER,
    unit_price    DOUBLE,
    customer_id   VARCHAR,
    country       VARCHAR,
    revenue       DOUBLE
);

-- Product taxonomy (built by scripts/build_taxonomy.py)
CREATE TABLE IF NOT EXISTS dim_product (
    stock_code             VARCHAR PRIMARY KEY,
    canonical_description  VARCHAR,
    category_id            INTEGER,
    category_name          VARCHAR,
    cluster_id             INTEGER,
    taxonomy_version       VARCHAR
);

-- Business decisions, one row per run
CREATE TABLE IF NOT EXISTS decision_log (
    run_id        VARCHAR,
    as_of_date    VARCHAR,
    mode          VARCHAR,
    decision_json TEXT,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Worker tasks generated from decisions
CREATE TABLE IF NOT EXISTS task_queue (
    run_id     VARCHAR,
    task_json  TEXT,
    status     VARCHAR DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- All agent artifacts (reports, decisions, forecasts, audits)
CREATE TABLE IF NOT EXISTS run_artifacts (
    run_id        VARCHAR,
    artifact_type VARCHAR,
    artifact_json TEXT,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Stage 3 — Product Taxonomy (`scripts/build_taxonomy.py`)

An optional enrichment step that clusters raw product descriptions into human-readable categories using embeddings:

```
raw descriptions (e.g. "PINK HEART SHAPE GLITTER DECORATION")
  ↓ regex cleaning — strip colours, pack sizes, quantities
  ↓ embed with SentenceTransformer (all-MiniLM-L6-v2, 384-dim vectors)
  ↓ K-means clustering (k=30, normalized embeddings)
  ↓ Claude labels each cluster → human category name (e.g. "Seasonal Decorations")
  ↓ persist to dim_product with taxonomy_version tag
```

The taxonomy is optional for the core workflow but would be used by the RAG tool for category-level SOP policy retrieval.

### Bounded Mode Data Access

A critical correctness property: in bounded mode, agents must not see future data. This is enforced at the `SQLTool` layer — not by prompting the LLM to be careful, but by programmatically injecting a date filter into every query:

```python
# sql_tool.py — enforced at execution time, not at prompt time
if self.mode == "bounded":
    sql = sql.replace(
        "FROM fact_sales",
        f"FROM fact_sales WHERE invoice_date <= '{self.as_of_date}'"
    )
```

This means even if an agent constructs a query without a date filter, the bounded cutoff is always respected. The filter is applied to the raw SQL before it hits DuckDB.

---

## 3. Agent Architecture

Each agent is a specialised class with a single responsibility. Agents communicate only through the shared `WorkflowState` — they never call each other directly.

### DataEngineerAgent

**Responsibility:** Raw data ingestion, cleaning, and quality validation.

**Inputs:** `RunContext` (run_id, as_of_date, mode)

**Process:**
1. Load `data/raw/data.csv` with pandas
2. Rename and cast columns to canonical schema
3. Derive `revenue = quantity × unit_price`
4. Run `ValidatorTool` → collect quality findings
5. Write cleaned data to `data/curated/fact_sales.parquet`
6. Load Parquet into DuckDB `fact_sales` table

**Outputs:** Row count, validation findings, Parquet path

**No LLM call.** This agent is entirely deterministic.

---

### AnalystAgent

**Responsibility:** SQL-grounded KPI computation and sales performance reporting.

**Inputs:** `RunContext`, `period_start`, `period_end`

**Process:**
1. Run SQL via `SQLTool` for each metric (every query is captured as `QueryEvidence`):
   - `total_revenue`, `total_orders`, `avg_order_value`, `unique_customers` — single aggregate query
   - `return_rate` — count of negative-quantity rows vs total
   - Top 10 SKUs by revenue — grouped by `stock_code` with canonical description subquery
   - Bottom 10 SKUs (min 5 units sold) by revenue
2. Pass SQL results + evidence to Claude with a strict system prompt: *all numbers must come from tool outputs, never from model knowledge*
3. LLM generates: anomalies (unusual patterns in the data), 3–5 sentence narrative summary
4. All KPI values are pre-populated from SQL — LLM cannot alter them

**Key design:** The LLM role here is strictly narrative and pattern recognition, not arithmetic. Numbers flow SQL → Pydantic schema → report. The LLM only fills `anomalies` and `narrative` fields.

**Output:** `AnalystReport`

```
AnalystReport
├── run_id, as_of_date, mode
├── period_start, period_end
├── kpis: list[KPI]           ← each KPI carries its QueryEvidence
├── top_skus: list[dict]      ← pre-computed by SQL, not LLM
├── bottom_skus: list[dict]
├── anomalies: list[Anomaly]  ← LLM pattern recognition only
├── narrative: str            ← LLM summary only
└── queries_executed: list[QueryEvidence]
```

---

### DataScientistAgent

**Responsibility:** Per-SKU demand forecasting with real holdout backtest evaluation.

**Inputs:** `RunContext`, `horizon_days=28`

**Process:**
1. Query top 20 SKUs by revenue via `SQLTool`
2. Query daily demand series for those SKUs (quantity > 0 only, grouped by date)
3. For each of the top 5 SKUs by revenue:
   - Build continuous daily series (reindex to fill missing dates)
   - Forward-fill gaps ≤ 6 consecutive days; zero-fill remainder
   - Select model based on series quality:

**Model selection logic:**

| Condition | Model Selected |
|---|---|
| Series ≥ 56 days AND ≥ 14 non-zero days | LightGBM |
| Otherwise | Improved Seasonal Naive |

**LightGBM pipeline:**
- Features: `day_of_week`, `week_of_year`, `month`, `lag_7`, `lag_14`, `lag_28`, `rolling_mean_7`, `rolling_mean_14`, `rolling_std_7`
- Train/test split: all-but-last-28 days for training, last 28 days for real holdout evaluation
- Backtest: MAPE and RMSE computed on the held-out 28-day window (not in-sample)
- Uncertainty bands: ±1.28 × training residual std (≈ 80% prediction interval)
- Forecast: recursive multi-step for horizon_days; each day's prediction fed back as lag for the next

**Improved Seasonal Naive pipeline:**
- Collect last 4 same-day-of-week values from training history
- Weighted average (weights: 2, 2, 1, 1 — more recent weeks weighted higher)
- Uncertainty bands: ±1.5 × same-DOW std (minimum ±0.5 units)
- Backtest: same 28-day holdout methodology as LightGBM

**No LLM call.** Forecasting is fully deterministic and numerical.

**Output:** `ForecastReport`

```
ForecastReport
├── model_name: "lightgbm" | "seasonal_naive"
├── horizon_days: 28
├── forecasts: list[ForecastRow]   ← 28 rows × 5 SKUs = 140 rows
│   └── ForecastRow: stock_code, ds, yhat, yhat_lower, yhat_upper
├── backtest_metrics: list[BacktestMetrics]
│   └── BacktestMetrics: stock_code, mape, rmse, train_start, train_end
├── assumptions: list[str]
└── queries_executed: list[QueryEvidence]
```

---

### ManagerAgent

**Responsibility:** Business decision-making from analyst KPIs and demand signals.

**Inputs:** `RunContext`, `AnalystReport`, `ForecastReport`

**Process:**
1. Compute average MAPE across all SKUs
2. Derive forecast reliability verdict:
   - avg MAPE ≤ 1.0 (100%) → **RELIABLE** — manager may cite specific forecast numbers
   - avg MAPE > 1.0 → **NOT RELIABLE** — manager must not cite specific quantities; directional guidance only (up/flat/down)
3. Pass analyst KPI summary + reliability verdict + forecast direction to Claude
4. LLM generates 3–7 business actions, each with: action_type, description, urgency, expected_impact
5. Pydantic validation + repair loop (up to 3 retries if schema fails)

**Action types:** `restock`, `markdown`, `reorder`, `promo`, `staffing`, `audit_returns`, `other`

**Key design:** The reliability gating is not prompt-only — it is computed deterministically and injected into the prompt as a hard rule. The LLM cannot decide for itself whether the forecast is reliable.

**Output:** `Decision`

```
Decision
├── actions: list[Action]
│   └── Action: action_type, stock_code, description, urgency, expected_impact
├── rationale: str
├── confidence: float (0.0–1.0)
├── risks: list[str]
├── kpi_references: list[str]
└── forecast_references: list[str]
```

---

### WorkerAgent

**Responsibility:** Translate manager decisions into executable, assignable task cards.

**Inputs:** `RunContext`, `Decision`

**Process:**
1. Pass all manager actions to Claude with routing rules:
   - `restock` / `reorder` → `warehouse_team`
   - `markdown` / `promo` → `marketing_team`
   - `staffing` → `hr_team`
   - `audit_returns` → `qa_team`
   - `other` → `ops_team`
2. LLM generates one `WorkerTask` per manager action:
   - Title, description, step-by-step checklist, acceptance criteria, expected outcome, due date, priority
3. Pydantic validation + repair loop

**Output:** `list[WorkerTask]`

```
WorkerTask
├── task_id (UUID), run_id
├── assigned_to: "warehouse_team" | "marketing_team" | "hr_team" | "qa_team" | "ops_team"
├── action_type: matches parent Action
├── title, description
├── priority: "low" | "medium" | "high"
├── due_date: str
├── checklist: list[ChecklistItem]   ← step-by-step instructions
└── acceptance_criteria: list[str]   ← definition of done
```

---

### AuditorAgent

**Responsibility:** Cross-check all agent outputs for factuality, grounding, and policy compliance.

**Inputs:** `RunContext`, `AnalystReport`, `ForecastReport`, `Decision`

**Process — deterministic checks first:**
1. Every KPI has a `QueryEvidence` entry
2. In bounded mode: `period_end` ≤ `as_of_date` (no future data leakage)
3. `Decision.actions` is non-empty and `Decision.rationale` is non-empty
4. `Decision.confidence` is a valid float between 0 and 1

**Process — LLM factuality audit:**
5. Pass all KPI values alongside their SQL evidence to Claude
6. LLM verifies: do the numbers in the narrative match the SQL output?
7. LLM checks: are any cited quantities not present in the evidence?
8. LLM checks: do decisions reference KPIs correctly?
9. LLM generates findings with severity (info / warning / error) and remediation recommendations

**Output:** `AuditReport`

```
AuditReport
├── passed: bool   ← True only if zero "error" severity findings
├── findings: list[AuditFinding]
│   └── AuditFinding: severity, finding_type, description,
│                      affected_field, reported_value, verified_value,
│                      recommendation
└── summary: str
```

**Finding types:** `number_mismatch`, `missing_citation`, `hallucinated_metric`, `policy_violation`, `schema_drift`, `other`

---

## 4. Workflow Orchestration

The full pipeline is modelled as a directed graph using LangGraph's `StateGraph`:

```
                    ┌─────────────────┐
                    │  data_engineer  │  (always runs first)
                    └────────┬────────┘
                             │
               ┌─────────────┴─────────────┐
               │                           │
               ▼                           ▼
          ┌─────────┐               ┌──────────────────┐
          │ analyst │               │ data_scientist   │
          └────┬────┘               └────────┬─────────┘
               │                             │
               └──────────┬──────────────────┘
                          │ (fan-in barrier)
                          ▼
                     ┌─────────┐
                     │ fan_in  │  ← both branches must complete
                     └────┬────┘    before this node runs
                          │
              ┌───────────┴──────────┐
              │ both reports present?│
              ├─ yes ──────────────► ┤
              │                      ▼
              │                ┌─────────┐
              │                │ manager │
              │                └────┬────┘
              │          ┌──────────┴──────────┐
              │          │ decision produced?  │
              │          ├─ yes ─────────────► ┤
              │          │                     ▼
              │          │               ┌────────┐
              │          │               │ worker │
              │          │               └───┬────┘
              │          │       ┌───────────┴───────────┐
              │          │       │ worker_tasks non-empty?│
              │          │       ├─ yes ────────────────► ┤
              │          │       │                        ▼
              │          │       │                  ┌─────────┐
              │          │       │                  │ auditor │
              │          │       │                  └────┬────┘
              │          │       │                       │
              └──────────┴───────┴───────────────────────┤
                                                         ▼
                                                   ┌─────────┐
                                                   │ persist │  ← always runs
                                                   └────┬────┘
                                                        ▼
                                                      (END)
```

### Fan-In Pattern

`analyst` and `data_scientist` run in parallel (both are reachable from `data_engineer` in the same superstep). The `fan_in` node acts as a barrier: LangGraph only executes it once all incoming edges have been activated, meaning both parallel branches must complete before the manager can proceed. Without this barrier, whichever branch finishes first would independently evaluate the routing condition and potentially short-circuit to `persist` before the other branch completes.

### Circuit Breakers

Every conditional edge implements a fail-safe: if an upstream artifact is missing (due to an exception in an agent), the pipeline skips downstream nodes and routes directly to `persist`. This ensures partial results are always saved even if one agent fails:

| After node | Condition | Routes to |
|---|---|---|
| `fan_in` | Both `analyst_report` AND `forecast_report` present | `manager` |
| `fan_in` | Either is None | `persist` |
| `manager` | `decision` is not None | `worker` |
| `manager` | `decision` is None | `persist` |
| `worker` | `worker_tasks` non-empty | `auditor` |
| `worker` | `worker_tasks` empty | `persist` |

### Shared State

All agents read from and write to a single `WorkflowState` object:

```python
class WorkflowState(TypedDict):
    ctx: RunContext                          # immutable run context
    de_summary: dict | None
    analyst_report: AnalystReport | None
    forecast_report: ForecastReport | None
    decision: Decision | None
    worker_tasks: list[WorkerTask] | None
    audit_report: AuditReport | None
    errors: list[str]                       # accumulated errors
```

### Repair Loop

When an LLM output fails Pydantic validation (malformed JSON, missing required fields, wrong types), the base agent class retries with a correction prompt:

```
Attempt 1: initial response → parse → ValidationError
Attempt 2: "Your previous response failed with: {error}. Fix it." → parse → ValidationError
Attempt 3: "Return ONLY valid JSON matching this schema: {schema}" → parse → success or give up
```

This handles the common LLM failure modes (markdown code fences around JSON, extra prose, wrong field names) without requiring a human in the loop.

---

## 5. Technology Stack & Design Decisions

### Orchestration

#### LangGraph — chosen over: plain Python, Airflow, Prefect, AutoGen

**Why LangGraph:**
LangGraph models the workflow as an explicit directed graph where each node is an agent and edges carry state. This makes control flow inspectable, debuggable, and easy to reason about. Conditional edges provide the circuit-breaker pattern without custom exception handling spread across agents.

**Why not plain Python (sequential function calls):**
State management becomes ad hoc. Parallel execution requires threading/asyncio boilerplate. No visual graph representation. Harder to add new agents or reorder the pipeline without restructuring code.

**Why not Airflow/Prefect:**
Those tools are designed for long-running batch pipelines with scheduling, retries, and distributed workers. The overhead (Airflow's DAG serialisation, Postgres metastore, scheduler process) is disproportionate for an in-process agent pipeline. LangGraph runs in the same Python process as the application.

**Why not AutoGen or CrewAI:**
AutoGen's multi-agent conversation model involves agents talking to each other in unstructured dialogue — suitable for open-ended problem solving, not suitable when you need deterministic, grounded outputs. CrewAI abstracts away too much of the routing logic. LangGraph gives explicit control over every edge and condition.

**Tradeoff:** LangGraph requires understanding its superstep execution model (particularly the fan-in pattern) to avoid race conditions. It also adds a dependency on the LangChain ecosystem.

---

#### LangChain Core + langchain-anthropic — chosen over: raw `anthropic` SDK, LiteLLM

**Why LangChain abstractions:**
`BaseChatModel` provides a unified interface across Claude, GPT-4o, and Ollama. Swapping providers is a one-line config change. Prompt templates, output parsers, and the retry logic in `call_with_repair` are reusable across all agents.

**Why not raw Anthropic SDK:**
Perfectly valid for a single-provider project. The cost is vendor lock-in and the need to rewrite if switching providers. Here the abstraction layer buys provider agnosticism at minimal overhead.

**Why not LiteLLM:**
LiteLLM is a thin HTTP proxy that translates OpenAI API calls to other providers. It works well for simple completions but doesn't integrate with LangGraph's graph execution or LangSmith tracing.

**Tradeoff:** LangChain's abstraction adds indirection. Debugging requires understanding both LangChain and the underlying SDK. LangChain also evolves rapidly — version pinning in `requirements.txt` is important.

---

### Data Layer

#### DuckDB — chosen over: SQLite, PostgreSQL, Polars, BigQuery

**Why DuckDB:**
DuckDB is an embedded analytical SQL engine optimised for OLAP workloads (aggregations, range scans, GROUP BY). It runs directly on Parquet files without a server process. Queries that would take seconds in SQLite (full-table scans, multi-column aggregations on 500K rows) run in milliseconds in DuckDB.

**Why not SQLite:**
SQLite is a row-oriented store optimised for transactional workloads (many small INSERT/UPDATE/SELECT by primary key). It performs poorly on analytical queries over wide tables with GROUP BY and aggregations — exactly what the analyst agent does.

**Why not PostgreSQL:**
Postgres requires a separate server process, connection pooling, and schema management tooling. For a local portfolio project, that overhead is unnecessary. DuckDB is a single file.

**Why not Polars (pure in-memory DataFrame):**
Polars doesn't give you SQL, which is the natural interface for the analyst's queries. It also doesn't provide a persistent on-disk store. DuckDB gives both SQL and persistence.

**Why not BigQuery/Snowflake:**
Cloud data warehouses require accounts, credentials, and network access. DuckDB achieves near-identical query expressiveness locally for a dataset of this size.

**Tradeoff:** DuckDB is single-process and not designed for concurrent writes. In a production system with multiple parallel runs, you'd need connection management or a proper database server.

---

#### Parquet — chosen over: CSV, Feather, HDF5

**Why Parquet:**
Column-oriented storage means only the columns needed for a query are read from disk. Efficient compression per column (dictionary encoding for stock_code, delta encoding for dates). DuckDB reads Parquet natively without loading it entirely into memory.

**Why not CSV:**
CSV is row-oriented, has no type information, and must be fully parsed before any query can run. Reading 541,909 rows from CSV takes ~400ms vs ~30ms from Parquet.

**Why not Feather/HDF5:**
Both are also columnar and fast, but Parquet has become the de facto standard in data engineering (supported by Spark, BigQuery, DuckDB, pandas, Polars). Feather is an in-memory-optimised format not suited for archival. HDF5 requires the h5py library and is less portable.

**Tradeoff:** Parquet files are binary and not human-readable. You need pandas or DuckDB to inspect them.

---

#### Pandas — used alongside DuckDB

Pandas is used for the ingest/cleaning stage where row-wise operations (type casting, column renaming, regex substitution) are ergonomic. DuckDB takes over for all analytical queries. This avoids loading the full dataset into a pandas DataFrame during every query — DuckDB reads from Parquet directly.

---

### Forecasting

#### LightGBM — chosen over: Prophet, ARIMA, Statsforecast, PyTorch/Darts

**Why LightGBM:**
Gradient-boosted trees with lag and calendar features outperform classical time-series models on retail demand data for several reasons: retail demand is non-stationary, exhibits complex day-of-week seasonality, and has structural breaks (promotions, stockouts) that violate ARIMA's stationarity assumptions. LightGBM handles all of this naturally as features. It's also fast to train (< 500ms per SKU on 200 days of data) and produces interpretable feature importances.

**Why not Prophet:**
Prophet was originally included in this project. It performed poorly on short (200-day) retail series because its Fourier-series seasonality decomposition needs longer history to stabilise. Its in-sample fit looked good but holdout MAPE was typically 30–80% — worse than LightGBM's 1–14% on the same series. Prophet also doesn't support lag features natively, which are the most informative signals for demand.

**Why not ARIMA/SARIMA:**
Classical Box-Jenkins models require stationarity testing, differencing, and manual order selection — significant tuning for potentially hundreds of SKUs. They also don't incorporate external regressors (calendar features) as naturally as tree models.

**Why not PyTorch / neural networks (LSTM, N-BEATS, Temporal Fusion Transformer):**
Neural networks require substantially more data (thousands of days) and compute to train reliably. On a 200-day series with 5 SKUs, they would overfit severely. They're the right tool at scale (thousands of SKUs, years of history) but inappropriate here.

**Why not Statsforecast (Nixtla):**
Excellent library for statistical baselines at scale. Would be a strong alternative if the project were evaluating many models across hundreds of SKUs. For this project scope, LightGBM with manual feature engineering provides a clearer demonstration of the modelling decisions.

**Seasonal Naive fallback:**
For SKUs with fewer than 56 training days or fewer than 14 non-zero demand days, LightGBM's lag features would be filled with zeros and the model would degenerate. The improved seasonal naive (4-week same-DOW weighted average) is the appropriate fallback — simple, interpretable, and robust on short series.

**Tradeoff:** LightGBM requires `libomp` on macOS (`brew install libomp`). The recursive multi-step forecast accumulates error across the 28-day horizon. A direct multi-output approach (training one model per horizon step) would be more accurate but 28× slower.

---

#### scikit-learn — for SKU taxonomy clustering

K-means on normalised sentence embeddings is used to cluster ~4,000 product descriptions into 30 categories. This is standard practice for unsupervised categorisation when no ground-truth labels exist. HDBSCAN (density-based, no fixed k) is a viable alternative that handles variable cluster density better — the tradeoff is that k-means is simpler and the resulting categories are more evenly sized.

---

### Backend

#### FastAPI — chosen over: Flask, Django, raw ASGI

**Why FastAPI:**
FastAPI generates OpenAPI/Swagger docs automatically from Pydantic models, which means the API is self-documenting. Async handlers (`async def`) are first-class. Pydantic request validation is built in. For a project already using Pydantic throughout, FastAPI is the natural backend.

**Why not Flask:**
Flask has no built-in async support, no automatic schema validation, and no OpenAPI generation. You'd need Flask-RESTX or apispec for docs.

**Why not Django:**
Django's ORM and admin panel are optimised for relational web apps with user authentication. For a stateless ML API serving agent workflow results, Django's overhead (settings modules, migrations, app registry) is unnecessary.

**Tradeoff:** FastAPI's async model means blocking calls (like LightGBM training) block the event loop if not run in a thread pool executor. The current implementation runs the workflow in a `BackgroundTask`, which is adequate for single-user demo use but would require proper task queuing (Celery, ARQ) in production.

---

#### Uvicorn — chosen over: Gunicorn, Hypercorn

Uvicorn is the standard ASGI server for FastAPI. For a local development setup, it's the correct choice. Production would add Gunicorn in front of multiple Uvicorn workers.

---

#### Pydantic v2 — used throughout

All agent inputs, outputs, and API request/response schemas are Pydantic models. This provides:
- Runtime validation with clear error messages (used in the repair loop)
- `.model_dump_json()` for serialisation to DuckDB
- `.model_validate()` for deserialisation from stored JSON
- Type annotations that IDEs and type checkers can verify

Pydantic v2 (Rust-based validator) is ~5–50× faster than v1 for validation-heavy workloads.

---

### Frontend

#### Streamlit — chosen over: React, Dash, Gradio, Panel

**Why Streamlit:**
The UI's purpose is to display structured data from agent runs — tables, charts, expandable JSON, metric cards. Streamlit's component model (top-to-bottom Python script) maps directly onto this. No JavaScript, no build step, no component lifecycle management.

**Why not React:**
A React frontend is appropriate when the UI needs complex interactivity, real-time updates, or shared state across many components. For a data display dashboard with a single action (trigger run, view results), the engineering overhead is disproportionate.

**Why not Dash (Plotly):**
Dash is callback-driven, which means wiring together multiple inputs/outputs requires registering `@app.callback` decorators. For simple sequential display, Streamlit is more readable.

**Why not Gradio:**
Gradio is optimised for model demos with a single input → output pattern. The multi-tab, multi-artifact display with run history selector and PDF export exceeds its natural scope.

**Tradeoff:** Streamlit reruns the entire script on every widget interaction, which can feel slow for pages with expensive computations. The project uses `st.session_state` to cache artifact fetches within a session.

---

#### fpdf2 — for PDF export

fpdf2 is a pure-Python PDF generation library. It produces reports without requiring a browser or headless Chrome (as would be needed with Playwright/WeasyPrint for HTML-to-PDF). The tradeoff is that it requires manual layout management (cell widths, line heights, page breaks) and only supports latin-1 characters natively — handled here with a `normalize_text` override that sanitises Unicode characters before rendering.

---

### Observability

#### structlog — chosen over: Python's `logging` module, loguru

structlog outputs structured JSON logs with key-value pairs per event. Every significant agent action emits a log entry with `run_id`, step name, and relevant metrics. This makes logs machine-queryable:

```
grep "data_scientist.model_selected" uvicorn.log
```

**LangSmith (optional):** If `LANGCHAIN_TRACING_V2=true` is set in `.env`, LangChain automatically traces every LLM call, prompt, and response to LangSmith. This provides token-level debugging of agent behaviour without any code changes.

---

### Model Providers

The LLM used by agents is configurable via `.env`:

| Provider | Default model | Notes |
|---|---|---|
| Anthropic (default) | `claude-haiku-4-5-20251001` | Best price/performance for structured output tasks |
| OpenAI | `gpt-4o-mini` | Alternative; similar capability tier |
| Ollama | `llama3.2` (configurable) | Free, local, no API key needed; lower quality on structured JSON |

The provider abstraction is `backend.app.agents.base.build_llm(settings)` — swapping providers requires only a `.env` change.

---

## 6. Core Learning Objectives

This project was designed to develop and demonstrate the following skills at a senior-practitioner level:

### Multi-Agent System Design

- Decomposing a business process into discrete, single-responsibility agents with clean interfaces
- Designing typed contracts (Pydantic schemas) so agents can consume each other's outputs without coupling
- Implementing the **fan-out / fan-in pattern** in LangGraph: parallel execution of independent agents followed by a barrier synchronisation before the next stage
- Using **circuit breakers** (conditional edges) to handle partial failures gracefully without crashing the pipeline

### Hallucination Prevention & Grounded Outputs

- Enforcing that all KPIs and numeric claims in reports **trace to a tool output** (SQL query evidence), never to LLM recall
- Building a **repair loop** that retries LLM calls with structured correction prompts when output validation fails
- Implementing an **Auditor Agent** that cross-verifies report numbers against their SQL evidence and flags mismatches with specific severity levels
- Distinguishing between what LLMs should generate (narrative, anomaly detection, task descriptions) vs what should be computed deterministically (KPIs, forecasts, routing decisions)

### Temporal Correctness & Backtesting

- Enforcing **point-in-time correctness** at the tool layer (not prompt layer) so agents in bounded mode cannot access future data
- Implementing **real holdout backtests** for forecasting models: training on all-but-last-28 days, evaluating on held-out 28 days
- Understanding the difference between in-sample fit (overly optimistic) and out-of-sample evaluation (realistic)
- Designing a framework to **compare decision quality** across information horizons (bounded vs omniscient)

### Demand Forecasting in Practice

- Selecting appropriate models based on series characteristics (length, sparsity)
- Engineering lag and calendar features for gradient-boosted tree models on time-series data
- Implementing **recursive multi-step forecasting** (predicting step 1, appending it to the series, predicting step 2, etc.)
- Propagating **uncertainty** through forecasts (residual standard deviation → prediction intervals)
- Gating downstream decisions on forecast reliability (MAPE threshold) so unreliable forecasts don't drive overconfident actions

### Data Engineering Fundamentals

- Building a **curated analytical layer** from raw CSV using a standard ETL pattern
- Understanding why columnar storage (Parquet) and embedded OLAP (DuckDB) outperform row stores for analytical queries
- Implementing **data quality validation** as a first-class step (schema checks, null audits, duplicate detection) before any analytical work
- Designing a **product taxonomy** using embeddings + clustering + LLM labelling — a real technique used for catalogue enrichment at e-commerce companies

### Production-Oriented Engineering Practices

- Separating concerns cleanly: agents (business logic) / tools (deterministic computation) / models (schemas) / graph (orchestration) / API (serving) / UI (display)
- Using **environment-based configuration** (Pydantic Settings) with no hardcoded secrets
- **Structured logging** with key-value pairs on every significant event for machine-queryable audit trails
- Assigning a `run_id` to every run and persisting all artifacts, queries, and decisions for full reproducibility
- Implementing an HTTP API with background task execution, polling endpoints, and OpenAPI documentation

### Evaluation & Comparison

- Designing an evaluation framework that compares bounded vs omniscient decisions on the same date
- Using backtest metrics (MAPE, RMSE) to quantify forecast quality, not just qualitative assessment
- Building an auditor that produces findings with severity, affected field, reported vs verified values, and recommendations — making errors actionable rather than just flagged

---

## 7. Project Structure

```
agent_project/
│
├── backend/
│   └── app/
│       ├── agents/                    # Agent class definitions
│       │   ├── base.py                # Shared utilities: build_llm, load_prompt, call_with_repair
│       │   ├── data_engineer_agent.py # Ingest, clean, validate raw data
│       │   ├── analyst_agent.py       # SQL-grounded KPI reporting
│       │   ├── data_scientist_agent.py# LightGBM + seasonal naive demand forecasting
│       │   ├── manager_agent.py       # Business decision generation
│       │   ├── worker_agent.py        # Task decomposition and assignment
│       │   ├── auditor_agent.py       # Factuality and grounding verification
│       │   └── prompts/               # Versioned YAML system/user prompts
│       │       ├── analyst.yaml
│       │       ├── manager.yaml
│       │       ├── worker.yaml
│       │       └── auditor.yaml
│       │
│       ├── api/
│       │   └── routes.py              # FastAPI route handlers
│       │
│       ├── core/
│       │   ├── config.py              # Pydantic Settings (reads .env)
│       │   ├── database.py            # DuckDB connection + schema init
│       │   └── logging.py             # structlog configuration
│       │
│       ├── graph/
│       │   ├── workflow.py            # LangGraph StateGraph definition + run_cycle()
│       │   └── state.py               # WorkflowState TypedDict
│       │
│       ├── models/
│       │   ├── run_context.py         # RunContext (run_id, dates, mode)
│       │   ├── reports.py             # AnalystReport, ForecastReport, KPI, QueryEvidence
│       │   ├── decisions.py           # Decision, Action, WorkerTask, ChecklistItem
│       │   └── audit.py               # AuditReport, AuditFinding
│       │
│       ├── tools/
│       │   ├── sql_tool.py            # SQL execution with bounded mode enforcement + evidence capture
│       │   ├── validator_tool.py      # Data quality checks on raw DataFrame
│       │   ├── python_tool.py         # Sandboxed Python computation
│       │   └── rag_tool.py            # Local document retrieval (SentenceTransformer + cosine sim)
│       │
│       └── main.py                    # FastAPI app factory + router registration
│
├── data/
│   ├── raw/
│   │   └── data.csv                   # Source: UCI Online Retail dataset
│   ├── curated/
│   │   ├── fact_sales.parquet         # Cleaned transaction data (auto-generated)
│   │   └── warehouse.duckdb           # DuckDB analytical warehouse (auto-generated)
│   └── docs/
│       ├── sop_restock_policy.md      # SOP: reorder triggers, approval thresholds, lead times
│       └── sop_markdown_policy.md     # SOP: markdown triggers, discount tiers, approval levels
│
├── evals/                             # Evaluation harnesses (forecast accuracy, factuality)
│
├── scripts/
│   ├── ingest.py                      # Build curated layer from raw CSV (run once)
│   ├── build_taxonomy.py              # Cluster SKUs into categories using embeddings + Claude
│   └── run_cycle.py                   # Run a full agent workflow from the CLI
│
├── ui/
│   ├── streamlit_app.py               # Streamlit UI entrypoint
│   ├── components/
│   │   ├── report_viewer.py           # Analyst + forecast display components
│   │   ├── decision_panel.py          # Decision, worker tasks, audit display
│   │   └── charts.py                  # Plotly forecast chart, KPI cards
│   └── utils/
│       └── pdf_export.py              # fpdf2-based executive PDF report generator
│
├── infra/
│   └── docker-compose.yml             # Optional: Postgres + pgvector setup
│
├── start.sh                           # One-command startup (ingest + backend + UI)
├── requirements.txt
├── .env.example
└── CLAUDE.md                          # Project instructions for LLM coding assistants
```

---

## 8. How to Run

### Prerequisites

- **Python 3.11+**
- **An API key** from [Anthropic](https://console.anthropic.com) (default), [OpenAI](https://platform.openai.com), or [Ollama](https://ollama.com) installed locally (free)
- **macOS only:** LightGBM requires OpenMP — install with `brew install libomp`

---

### Step 1 — Clone the repository

```bash
git clone <https://github.com/alvinn6o/Agentic-AI-Retail.git>
cd agent_project
```

---

### Step 2 — Create and activate a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows
```

Your terminal prompt will show `(.venv)` when the environment is active.

---

### Step 3 — Install dependencies

```bash
pip install -r requirements.txt
```

On macOS, if LightGBM fails to import later:

```bash
brew install libomp
```

---

### Step 4 — Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and set your LLM provider and API key:

```bash
# ── LLM Provider ─────────────────────────────────────────────────────────────
LLM_PROVIDER=anthropic                   # anthropic | openai | ollama

# Anthropic (recommended — get key at console.anthropic.com)
ANTHROPIC_API_KEY=sk-ant-...

# OpenAI (alternative — get key at platform.openai.com)
# OPENAI_API_KEY=sk-...

# Ollama (free, local — install ollama first, then: ollama pull llama3.2)
# LLM_PROVIDER=ollama
# OLLAMA_BASE_URL=http://localhost:11434
# OLLAMA_MODEL=llama3.2

# ── Data paths (defaults work for local dev) ──────────────────────────────────
DUCKDB_PATH=data/curated/warehouse.duckdb
RAW_DATA_PATH=data/raw/data.csv
CURATED_PATH=data/curated
DOCS_PATH=data/docs

# ── Embedding model for RAG tool and taxonomy builder ─────────────────────────
EMBEDDING_MODEL=all-MiniLM-L6-v2

# ── Agent behaviour ───────────────────────────────────────────────────────────
LOG_LEVEL=INFO
MAX_REPAIR_RETRIES=3

# ── Optional: LangSmith tracing (langsmith.com) ───────────────────────────────
# LANGCHAIN_TRACING_V2=true
# LANGCHAIN_API_KEY=ls__...
# LANGCHAIN_PROJECT=retail-ops-simulator
```

---

### Step 5 — Add the source data

Download the UCI Online Retail dataset and place the CSV at:

```
data/raw/data.csv
```

Expected columns: `InvoiceNo, StockCode, Description, Quantity, InvoiceDate, UnitPrice, CustomerID, Country`

The file should be latin-1 encoded (standard for the UCI dataset export).

---

### Step 6 — Start everything

```bash
bash start.sh
```

This script:
1. Checks that `.env` exists
2. Runs `scripts/ingest.py` to build the DuckDB warehouse (skipped if already built)
3. Starts the FastAPI backend on `http://localhost:8000`
4. Starts the Streamlit UI on `http://localhost:8501`

Press `Ctrl+C` to stop all services cleanly.

---

### Running services individually

Useful when debugging or making code changes:

```bash
# Terminal 1 — Backend API (with auto-reload on file changes)
source .venv/bin/activate
uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000

# Terminal 2 — Streamlit UI
source .venv/bin/activate
streamlit run ui/streamlit_app.py --server.port 8501

# Run ingest only (first time, or after the source CSV changes)
python scripts/ingest.py

# Force re-ingest even if warehouse already exists
bash start.sh --reingest
```

---

### Running a workflow cycle from the CLI

```bash
# Bounded mode — agents see data up to 2011-06-30 only
python scripts/run_cycle.py --as_of 2011-06-30 --mode bounded

# Omniscient mode — agents see the full dataset
python scripts/run_cycle.py --as_of 2011-06-30 --mode omniscient

# Custom analysis window (bounded mode, 90-day window)
python scripts/run_cycle.py \
  --as_of 2011-06-30 \
  --start 2011-04-01 \
  --mode bounded

# Skip data ingest (if warehouse is already built)
python scripts/run_cycle.py --as_of 2011-06-30 --mode bounded --skip_ingest
```

---

### Triggering a run via the API directly

```bash
# Trigger a run
curl -X POST http://localhost:8000/api/v1/run \
  -H "Content-Type: application/json" \
  -d '{
    "as_of_date": "2011-06-30",
    "start_date": "2011-04-01",
    "mode": "bounded"
  }'
# → {"run_id": "abc123...", "status": "running"}

# Poll status
curl http://localhost:8000/api/v1/run/abc123.../status

# Fetch all artifacts
curl http://localhost:8000/api/v1/run/abc123.../artifacts

# List recent runs
curl http://localhost:8000/api/v1/runs?limit=20
```

---

### Build the product taxonomy (optional)

This step clusters product descriptions into categories and requires an Anthropic API key for the cluster labelling step:

```bash
python scripts/build_taxonomy.py
```

This writes results to `dim_product` in the DuckDB warehouse. The taxonomy is used by the RAG tool for policy retrieval but is not required for the core agent pipeline.

---

### Running tests

```bash
# All tests
pytest

# Specific test file
pytest evals/test_forecast_accuracy.py -v

# With coverage report
pytest --cov=backend --cov-report=term-missing
```

---

### Accessing the running application

| Service | URL | Notes |
|---|---|---|
| Streamlit UI | http://localhost:8501 | Main interface for running cycles and viewing results |
| FastAPI backend | http://localhost:8000 | REST API |
| API docs (Swagger) | http://localhost:8000/docs | Interactive API documentation, auto-generated |
| API docs (ReDoc) | http://localhost:8000/redoc | Alternative API docs format |

---

## 9. API Reference

### `POST /api/v1/run`

Trigger a new agent workflow cycle. The run executes asynchronously in the background.

**Request body:**

```json
{
  "as_of_date": "2011-06-30",
  "start_date": "2011-04-01",
  "mode": "bounded"
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `as_of_date` | `YYYY-MM-DD` | Yes | The "as of" date for bounded mode. Must be within 2010-12-01 → 2011-12-09. |
| `start_date` | `YYYY-MM-DD` | Yes | Start of analysis window. Must be before `as_of_date`. |
| `mode` | `"bounded"` or `"omniscient"` | Yes | `bounded` = agents see data up to `as_of_date` only. `omniscient` = full dataset visible. |

**Response:**

```json
{
  "run_id": "8e5ae99d-afb1-4e5c-943f-02ff3dff0190",
  "status": "running",
  "message": "Run started"
}
```

---

### `GET /api/v1/run/{run_id}/status`

Poll the status of a running or completed workflow.

**Response:**

```json
{
  "run_id": "8e5ae99d-afb1-4e5c-943f-02ff3dff0190",
  "status": "completed",
  "errors": []
}
```

`status` is one of: `running`, `completed`, `failed`

---

### `GET /api/v1/run/{run_id}/artifacts`

Retrieve all persisted artifacts for a completed run.

**Response:**

```json
{
  "run_id": "...",
  "analyst_report": { "kpis": [...], "top_skus": [...], ... },
  "forecast_report": { "model_name": "lightgbm", "forecasts": [...], ... },
  "decision": { "actions": [...], "rationale": "...", "confidence": 0.82 },
  "audit_report": { "passed": false, "findings": [...] },
  "worker_tasks": [{ "title": "...", "checklist": [...] }, ...]
}
```

---

### `GET /api/v1/runs`

List recent runs from the decision log.

**Query parameters:** `limit` (default: 20)

**Response:**

```json
[
  {
    "run_id": "...",
    "as_of_date": "2011-06-30",
    "mode": "bounded",
    "created_at": "2026-02-20T22:40:42Z"
  }
]
```

---

## 10. Configuration Reference

All settings are read from `.env` via Pydantic Settings. Values set in the environment override `.env`.

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `anthropic` | Model provider: `anthropic`, `openai`, `ollama` |
| `ANTHROPIC_API_KEY` | — | Anthropic API key (required if provider=anthropic) |
| `OPENAI_API_KEY` | — | OpenAI API key (required if provider=openai) |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL (required if provider=ollama) |
| `OLLAMA_MODEL` | `llama3.2` | Ollama model name |
| `DEFAULT_MODEL_ANTHROPIC` | `claude-haiku-4-5-20251001` | Claude model ID to use |
| `DEFAULT_MODEL_OPENAI` | `gpt-4o-mini` | OpenAI model ID to use |
| `DUCKDB_PATH` | `data/curated/warehouse.duckdb` | Path to DuckDB warehouse file |
| `RAW_DATA_PATH` | `data/raw/data.csv` | Path to source CSV |
| `CURATED_PATH` | `data/curated` | Directory for Parquet output |
| `DOCS_PATH` | `data/docs` | Directory containing SOP markdown documents |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | SentenceTransformer model for RAG and taxonomy |
| `LOG_LEVEL` | `INFO` | structlog level: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `MAX_REPAIR_RETRIES` | `3` | Max LLM repair attempts on schema validation failure |
| `LANGCHAIN_TRACING_V2` | — | Set to `true` to enable LangSmith tracing |
| `LANGCHAIN_API_KEY` | — | LangSmith API key |
| `LANGCHAIN_PROJECT` | — | LangSmith project name |

---

## License

MIT
