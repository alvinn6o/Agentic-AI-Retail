#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DUCKDB_PATH="$PROJECT_ROOT/data/curated/warehouse.duckdb"

cd "$PROJECT_ROOT"

# ── 1. .env check ──────────────────────────────────────────────────────────────
if [ ! -f ".env" ]; then
  if [ -f ".env.example" ]; then
    echo "[setup] .env not found — copying from .env.example"
    cp .env.example .env
    echo "[setup] Edit .env and set your API key, then re-run this script."
    exit 1
  else
    echo "[error] No .env or .env.example found. Cannot continue."
    exit 1
  fi
fi

# ── 2. Ingest (skip if warehouse already exists) ───────────────────────────────
if [ ! -f "$DUCKDB_PATH" ]; then
  echo "[ingest] warehouse.duckdb not found — running ingest..."
  python scripts/ingest.py
  echo "[ingest] Done."
else
  echo "[ingest] Warehouse already exists, skipping. Pass --reingest to force."
  if [[ "${1:-}" == "--reingest" ]]; then
    echo "[ingest] --reingest flag detected, re-running ingest..."
    python scripts/ingest.py
    echo "[ingest] Done."
  fi
fi

# ── 3. Start backend ───────────────────────────────────────────────────────────
echo "[backend] Starting FastAPI on http://localhost:8000 ..."
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

# Give the backend a moment to bind
sleep 2

# ── 4. Start UI ────────────────────────────────────────────────────────────────
echo "[ui] Starting Streamlit on http://localhost:8501 ..."
streamlit run ui/streamlit_app.py --server.port 8501 &
STREAMLIT_PID=$!

echo ""
echo "  Backend : http://localhost:8000"
echo "  API docs: http://localhost:8000/docs"
echo "  UI      : http://localhost:8501"
echo ""
echo "Press Ctrl+C to stop all services."

# ── 5. Cleanup on exit ─────────────────────────────────────────────────────────
cleanup() {
  echo ""
  echo "[shutdown] Stopping services..."
  kill "$BACKEND_PID" 2>/dev/null || true
  kill "$STREAMLIT_PID" 2>/dev/null || true
  wait "$BACKEND_PID" "$STREAMLIT_PID" 2>/dev/null || true
  echo "[shutdown] All services stopped."
}
trap cleanup INT TERM

wait "$BACKEND_PID" "$STREAMLIT_PID"
