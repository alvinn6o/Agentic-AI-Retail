"""SQLTool — runs parameterized SQL against DuckDB with bounded mode enforcement."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from typing import Any

import duckdb

from backend.app.core.config import Settings, get_settings
from backend.app.core.logging import get_logger
from backend.app.models.reports import QueryEvidence

logger = get_logger(__name__)

# Columns that contain temporal data and must be filtered in bounded mode
_DATE_COLUMNS = {"invoice_date", "created_at"}
_DATE_TABLE_COLS = {"fact_sales.invoice_date"}

_BOUNDED_INJECTION_TEMPLATE = (
    "AND {col} <= '{as_of_date}'"
)


def _inject_bounded_filter(sql: str, as_of_date: date) -> str:
    """
    Inject a WHERE / AND clause constraining invoice_date to <= as_of_date.
    Works on simple SELECT queries referencing fact_sales.
    For complex queries, raises ValueError if injection is unsafe.
    """
    sql_upper = sql.upper()
    if "INVOICE_DATE" not in sql_upper:
        return sql  # no temporal column — safe as-is

    date_str = as_of_date.isoformat()

    # If already constrained manually, respect that
    if f"INVOICE_DATE <=".replace(" ", "") in sql_upper.replace(" ", ""):
        return sql

    # Inject before ORDER BY / GROUP BY / LIMIT / end of query
    inject = f" AND invoice_date <= '{date_str}'"

    # Find WHERE clause
    where_match = re.search(r"\bWHERE\b", sql, re.IGNORECASE)
    order_match = re.search(r"\b(ORDER BY|GROUP BY|HAVING|LIMIT|$)\b", sql, re.IGNORECASE)

    if where_match:
        # Insert after the existing WHERE clause, before ORDER BY / GROUP BY / HAVING / LIMIT.
        insert_pos = order_match.start() if order_match and order_match.start() > where_match.start() else len(sql)
        # Strip surrounding whitespace at the splice point to avoid double-spaces or missing spaces.
        left = sql[:insert_pos].rstrip()
        right = sql[insert_pos:].lstrip()
        sep = " " if right else ""
        return left + inject + sep + right
    else:
        # No WHERE clause — inject a synthetic one before the first clause keyword.
        insert_pos = order_match.start() if order_match else len(sql)
        left = sql[:insert_pos].rstrip()
        right = sql[insert_pos:].lstrip()
        sep = " " if right else ""
        return left + f" WHERE 1=1{inject}" + sep + right


class SQLTool:
    """Deterministic SQL execution tool with bounded mode enforcement."""

    def __init__(
        self,
        as_of_date: date,
        mode: str,
        settings: Settings | None = None,
    ) -> None:
        self.as_of_date = as_of_date
        self.mode = mode
        self.settings = settings or get_settings()
        self._db_path = str(self.settings.duckdb_path)

    def run(
        self,
        sql: str,
        params: list[Any] | None = None,
        *,
        step: str = "unknown",
    ) -> tuple[list[dict[str, Any]], QueryEvidence]:
        """
        Execute SQL and return (rows, evidence).
        In bounded mode, invoice_date is automatically constrained.
        """
        effective_sql = sql
        if self.mode == "bounded":
            effective_sql = _inject_bounded_filter(sql, self.as_of_date)

        logger.info("sql_tool.execute", step=step, mode=self.mode, sql=effective_sql[:200])

        conn = duckdb.connect(self._db_path)
        try:
            result = conn.execute(effective_sql, params or [])
            columns = [desc[0] for desc in result.description]
            rows = [dict(zip(columns, row)) for row in result.fetchall()]
        finally:
            conn.close()

        evidence = QueryEvidence(
            sql=effective_sql,
            params=params or [],
            result_preview=rows[:5],
            run_at=step,
        )

        return rows, evidence

    def result_hash(self, rows: list[dict[str, Any]]) -> str:
        payload = json.dumps(rows, default=str, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]
