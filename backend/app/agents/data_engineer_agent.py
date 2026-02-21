"""DataEngineerAgent — refreshes curated data and checks quality."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from backend.app.core.config import Settings, get_settings
from backend.app.core.database import initialize_schema
from backend.app.core.logging import get_logger
from backend.app.models.run_context import RunContext
from backend.app.tools.validator_tool import ValidatorTool

logger = get_logger(__name__)


class DataEngineerAgent:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.validator = ValidatorTool()

    def ingest(self, ctx: RunContext) -> dict[str, object]:
        """
        Load raw CSV, clean, validate, write curated Parquet and populate DuckDB.
        Returns a summary dict with row counts and any validation findings.
        """
        raw_path = self.settings.raw_data_path
        if not raw_path.exists():
            raise FileNotFoundError(f"Raw data not found at {raw_path}")

        logger.info("de_agent.loading_csv", path=str(raw_path))
        df = pd.read_csv(raw_path, encoding="latin-1")

        # --- Clean ---
        df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
        df = df.rename(columns={"invoiceno": "invoice_no", "stockcode": "stock_code",
                                 "invoicedate": "invoice_date", "unitprice": "unit_price",
                                 "customerid": "customer_id"})

        df["invoice_date"] = pd.to_datetime(df["invoice_date"], infer_datetime_format=True)
        df["unit_price"] = pd.to_numeric(df["unit_price"], errors="coerce").fillna(0.0)
        df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").fillna(0).astype(int)
        df["customer_id"] = df["customer_id"].fillna("UNKNOWN").astype(str)
        df["stock_code"] = df["stock_code"].astype(str).str.strip()
        df["description"] = df["description"].fillna("").str.strip()
        df["revenue"] = df["quantity"] * df["unit_price"]

        # --- Validate ---
        findings = self.validator.validate_fact_sales(df)
        logger.info("de_agent.validation", num_findings=len(findings))

        # --- Write Parquet ---
        curated_path = self.settings.curated_path
        curated_path.mkdir(parents=True, exist_ok=True)
        parquet_path = curated_path / "fact_sales.parquet"
        df.to_parquet(parquet_path, index=False)
        logger.info("de_agent.parquet_written", path=str(parquet_path), rows=len(df))

        # --- Load into DuckDB ---
        db_path = self.settings.duckdb_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = duckdb.connect(str(db_path))
        initialize_schema(conn)

        conn.execute("DELETE FROM fact_sales")
        conn.execute(f"""
            INSERT INTO fact_sales
                (invoice_no, invoice_date, stock_code, description,
                 quantity, unit_price, customer_id, country, revenue)
            SELECT invoice_no, invoice_date, stock_code, description,
                   quantity, unit_price, customer_id, country, revenue
            FROM read_parquet('{parquet_path}')
        """)

        row_count = conn.execute("SELECT COUNT(*) FROM fact_sales").fetchone()[0]
        conn.close()

        logger.info("de_agent.duckdb_loaded", rows=row_count)
        return {
            "rows_loaded": row_count,
            "validation_findings": findings,
            "parquet_path": str(parquet_path),
        }
