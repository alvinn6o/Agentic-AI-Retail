"""Tests for deterministic tools."""

from __future__ import annotations

from datetime import date

import pytest

from backend.app.tools.sql_tool import _inject_bounded_filter


class TestBoundedFilter:
    """Test bounded mode SQL injection."""

    def test_adds_where_clause(self) -> None:
        # invoice_date must appear in the query for injection to trigger
        sql = "SELECT invoice_date, stock_code FROM fact_sales"
        result = _inject_bounded_filter(sql, date(2011, 6, 30))
        assert "invoice_date <= '2011-06-30'" in result

    def test_adds_and_to_existing_where(self) -> None:
        sql = "SELECT invoice_date, stock_code FROM fact_sales WHERE country = 'UK'"
        result = _inject_bounded_filter(sql, date(2011, 6, 30))
        assert "invoice_date <= '2011-06-30'" in result
        assert "country = 'UK'" in result

    def test_no_injection_when_no_date_column(self) -> None:
        sql = "SELECT stock_code, COUNT(*) FROM dim_product GROUP BY stock_code"
        result = _inject_bounded_filter(sql, date(2011, 6, 30))
        assert result == sql

    def test_no_double_injection(self) -> None:
        sql = "SELECT * FROM fact_sales WHERE invoice_date <= '2011-01-01'"
        result = _inject_bounded_filter(sql, date(2011, 6, 30))
        # Should not add another constraint
        assert result.count("invoice_date <=") <= 1

    def test_injects_before_order_by(self) -> None:
        sql = "SELECT * FROM fact_sales ORDER BY invoice_date"
        result = _inject_bounded_filter(sql, date(2011, 6, 30))
        date_pos = result.lower().index("invoice_date <=")
        order_pos = result.lower().index("order by")
        assert date_pos < order_pos
