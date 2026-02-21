"""FastAPI routes for triggering runs and retrieving artifacts."""

from __future__ import annotations

import json
import uuid
from datetime import date
from typing import Any, Literal

import duckdb
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, model_validator

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger
from backend.app.graph.workflow import run_cycle

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1")


# Valid date range of the underlying dataset
_DATA_MIN = date(2010, 12, 1)
_DATA_MAX = date(2011, 12, 9)


class RunRequest(BaseModel):
    start_date: date
    as_of_date: date
    mode: Literal["bounded", "omniscient"] = "bounded"
    skip_ingest: bool = False

    @model_validator(mode="after")
    def validate_dates(self) -> "RunRequest":
        if self.start_date >= self.as_of_date:
            raise ValueError("start_date must be before as_of_date")
        if self.start_date < _DATA_MIN:
            raise ValueError(f"start_date cannot be before {_DATA_MIN} (dataset start)")
        if self.as_of_date > _DATA_MAX:
            raise ValueError(f"as_of_date cannot be after {_DATA_MAX} (dataset end)")
        return self


class RunResponse(BaseModel):
    run_id: str
    status: str
    message: str


# In-memory run status (for demo; use Redis/DB for production)
_run_status: dict[str, dict[str, Any]] = {}


@router.post("/run", response_model=RunResponse)
async def trigger_run(req: RunRequest, background_tasks: BackgroundTasks) -> RunResponse:
    """Start a business cycle run in the background."""
    run_id = str(uuid.uuid4())
    _run_status[run_id] = {"status": "running", "run_id": run_id}

    def _run() -> None:
        try:
            state = run_cycle(
                req.as_of_date,
                req.mode,
                start_date=req.start_date,
                skip_ingest=req.skip_ingest,
                run_id=run_id,
            )
            _run_status[run_id]["status"] = "completed"
            _run_status[run_id]["errors"] = state.get("errors") or []
        except Exception as exc:
            logger.error("api.run.error", run_id=run_id, error=str(exc))
            _run_status[run_id]["status"] = "failed"
            _run_status[run_id]["error"] = str(exc)

    background_tasks.add_task(_run)
    return RunResponse(run_id=run_id, status="running", message="Run started")


@router.get("/run/{run_id}/status")
def get_run_status(run_id: str) -> dict[str, Any]:
    if run_id not in _run_status:
        # Check DB
        settings = get_settings()
        conn = duckdb.connect(str(settings.duckdb_path))
        rows = conn.execute(
            "SELECT run_id FROM run_artifacts WHERE run_id = ? LIMIT 1", [run_id]
        ).fetchall()
        conn.close()
        if rows:
            return {"run_id": run_id, "status": "completed"}
        raise HTTPException(status_code=404, detail="Run not found")
    return _run_status[run_id]


@router.get("/run/{run_id}/artifacts")
def get_artifacts(run_id: str) -> dict[str, Any]:
    """Return all persisted artifacts for a run."""
    settings = get_settings()
    conn = duckdb.connect(str(settings.duckdb_path))
    rows = conn.execute(
        "SELECT artifact_type, artifact_json FROM run_artifacts WHERE run_id = ?",
        [run_id],
    ).fetchall()
    conn.close()

    if not rows:
        raise HTTPException(status_code=404, detail="No artifacts found for run_id")

    result: dict[str, Any] = {"run_id": run_id}
    for artifact_type, artifact_json in rows:
        result[artifact_type] = json.loads(artifact_json)
    return result


@router.get("/runs")
def list_runs(limit: int = 20) -> list[dict[str, Any]]:
    """List recent runs."""
    settings = get_settings()
    try:
        conn = duckdb.connect(str(settings.duckdb_path))
        rows = conn.execute(
            """
            SELECT
                d.run_id,
                d.as_of_date,
                d.mode,
                d.created_at,
                ra.artifact_json ->> '$.period_start' AS period_start,
                ra.artifact_json ->> '$.period_end'   AS period_end
            FROM decision_log d
            LEFT JOIN run_artifacts ra
                ON d.run_id = ra.run_id AND ra.artifact_type = 'analyst_report'
            ORDER BY d.created_at DESC
            LIMIT ?
            """,
            [limit],
        ).fetchall()
        conn.close()
        return [
            {
                "run_id": r[0],
                "as_of_date": str(r[1]),
                "mode": r[2],
                "created_at": str(r[3]),
                "period_start": str(r[4]) if r[4] else None,
                "period_end": str(r[5]) if r[5] else None,
            }
            for r in rows
        ]
    except Exception:
        return []
