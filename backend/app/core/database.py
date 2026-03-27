"""DuckDB connection management."""

from pathlib import Path
from typing import Any

import duckdb

from backend.app.core.config import Settings, get_settings


def get_connection(settings: Settings | None = None) -> duckdb.DuckDBPyConnection:
    s = settings or get_settings()
    s.duckdb_path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(s.duckdb_path))


def execute_query(
    sql: str,
    params: list[Any] | None = None,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """Execute a SQL query and return rows as list of dicts."""
    conn = get_connection(settings)
    try:
        result = conn.execute(sql, params or [])
        columns = [desc[0] for desc in result.description]
        rows = result.fetchall()
        return [dict(zip(columns, row)) for row in rows]
    finally:
        conn.close()


def table_exists(table_name: str, settings: Settings | None = None) -> bool:
    rows = execute_query(
        "SELECT count(*) as cnt FROM information_schema.tables WHERE table_name = ?",
        [table_name],
        settings,
    )
    return rows[0]["cnt"] > 0 if rows else False


def initialize_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """Create core tables if they don't exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fact_sales (
            invoice_no   VARCHAR,
            invoice_date TIMESTAMP,
            stock_code   VARCHAR,
            description  VARCHAR,
            quantity     INTEGER,
            unit_price   DOUBLE,
            customer_id  VARCHAR,
            country      VARCHAR,
            revenue      DOUBLE
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS dim_product (
            stock_code            VARCHAR PRIMARY KEY,
            canonical_description VARCHAR,
            category_id           INTEGER,
            category_name         VARCHAR,
            cluster_id            INTEGER,
            taxonomy_version      VARCHAR
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS decision_log (
            run_id       VARCHAR,
            as_of_date   DATE,
            mode         VARCHAR,
            decision_json JSON,
            created_at   TIMESTAMP DEFAULT current_timestamp
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS task_queue (
            run_id     VARCHAR,
            task_json  JSON,
            status     VARCHAR DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT current_timestamp
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            run_id      VARCHAR,
            step        VARCHAR,
            tool_name   VARCHAR,
            sql_text    VARCHAR,
            params_json JSON,
            result_hash VARCHAR,
            created_at  TIMESTAMP DEFAULT current_timestamp
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS run_artifacts (
            run_id        VARCHAR,
            artifact_type VARCHAR,
            artifact_json JSON,
            created_at    TIMESTAMP DEFAULT current_timestamp
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS dispatch_log (
            run_id          VARCHAR,
            task_id         VARCHAR,
            target_system   VARCHAR,
            dispatch_status VARCHAR,
            payload_json    JSON,
            response_json   JSON,
            created_at      TIMESTAMP DEFAULT current_timestamp
        )
    """)
