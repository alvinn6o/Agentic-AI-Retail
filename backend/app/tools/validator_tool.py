"""ValidatorTool — data quality and schema drift checks."""

from __future__ import annotations

from typing import Any

import pandas as pd

from backend.app.core.logging import get_logger

logger = get_logger(__name__)


class ValidatorTool:
    """Checks DataFrames for quality issues and schema drift."""

    FACT_SALES_SCHEMA = {
        "invoice_no": "object",
        "invoice_date": "datetime64[ns]",
        "stock_code": "object",
        "description": "object",
        "quantity": "int64",
        "unit_price": "float64",
        "customer_id": "object",
        "country": "object",
        "revenue": "float64",
    }

    def validate_fact_sales(self, df: pd.DataFrame) -> list[dict[str, Any]]:
        """Return a list of findings (empty = clean)."""
        findings: list[dict[str, Any]] = []

        # Missing columns
        expected = set(self.FACT_SALES_SCHEMA.keys())
        actual = set(df.columns.str.lower())
        missing = expected - actual
        if missing:
            findings.append({"type": "missing_columns", "columns": sorted(missing)})

        # Null checks
        for col in expected & actual:
            null_count = int(df[col].isna().sum())
            if null_count > 0:
                findings.append({"type": "nulls", "column": col, "count": null_count})

        # Negative quantity / price
        if "quantity" in actual:
            neg = int((df["quantity"] < 0).sum())
            if neg > 0:
                findings.append({"type": "negative_quantity", "count": neg})

        if "unit_price" in actual:
            neg = int((df["unit_price"] < 0).sum())
            if neg > 0:
                findings.append({"type": "negative_unit_price", "count": neg})

        # Duplicate invoice lines
        if {"invoice_no", "stock_code"}.issubset(actual):
            dups = int(df.duplicated(subset=["invoice_no", "stock_code"]).sum())
            if dups > 0:
                findings.append({"type": "duplicate_invoice_lines", "count": dups})

        logger.info("validator_tool.done", num_findings=len(findings))
        return findings
