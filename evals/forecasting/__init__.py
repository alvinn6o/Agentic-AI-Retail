"""Forecasting evaluation: compare stored forecast vs actuals in fact_sales."""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import duckdb
import numpy as np

from backend.app.core.logging import get_logger
from backend.app.models.reports import BacktestMetrics, ForecastReport

logger = get_logger(__name__)


@dataclass
class SKUForecastAccuracy:
    stock_code: str
    forecast_horizon_days: int
    backtest_mape: float | None         # stored in ForecastReport (model self-reported)
    actual_mape: float | None           # recomputed from fact_sales actuals
    actual_rmse: float | None
    backtest_is_reliable: bool | None   # True if actual_mape <= 2x backtest_mape
    n_actuals: int                       # days of actuals found beyond as_of_date


@dataclass
class ForecastEvalResult:
    run_id: str
    as_of_date: str
    model_name: str
    total_skus_forecasted: int
    skus_with_actuals: int
    overall_actual_mape: float | None
    overall_actual_rmse: float | None
    per_sku: list[SKUForecastAccuracy] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _load_forecast_report(run_id: str, duckdb_path: str) -> ForecastReport:
    conn = duckdb.connect(duckdb_path, read_only=True)
    try:
        rows = conn.execute(
            """
            SELECT artifact_json FROM run_artifacts
            WHERE run_id = ? AND artifact_type = 'forecast_report'
            ORDER BY created_at DESC LIMIT 1
            """,
            [run_id],
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        raise ValueError(f"No forecast_report artifact found for run_id={run_id}")

    raw = rows[0][0]
    data = json.loads(raw) if isinstance(raw, str) else raw
    return ForecastReport.model_validate(data)


def _fetch_actuals(
    stock_codes: list[str],
    as_of_date: str,
    horizon_days: int,
    duckdb_path: str,
) -> dict[str, dict[str, float]]:
    """
    Fetch actual daily units from fact_sales for SKUs AFTER as_of_date, up to horizon_days.
    Returns {stock_code: {date_str: units}}.
    """
    if not stock_codes:
        return {}

    codes_placeholder = ", ".join(f"'{c}'" for c in stock_codes)
    sql = f"""
        SELECT
            stock_code,
            CAST(invoice_date AS DATE)::VARCHAR AS sale_date,
            SUM(quantity)                        AS daily_units
        FROM fact_sales
        WHERE stock_code IN ({codes_placeholder})
          AND quantity > 0
          AND CAST(invoice_date AS DATE) > DATE '{as_of_date}'
          AND CAST(invoice_date AS DATE) <= DATE '{as_of_date}' + INTERVAL '{horizon_days} days'
        GROUP BY stock_code, CAST(invoice_date AS DATE)
        ORDER BY stock_code, sale_date
    """
    conn = duckdb.connect(duckdb_path, read_only=True)
    try:
        rows = conn.execute(sql).fetchall()
    except Exception as exc:
        logger.warning("forecast_eval.actuals_fetch_failed", error=str(exc))
        return {}
    finally:
        conn.close()

    result: dict[str, dict[str, float]] = {}
    for row in rows:
        code, dt_str, units = row[0], str(row[1]), float(row[2])
        result.setdefault(code, {})[dt_str] = units
    return result


def _compute_mape_rmse(
    forecasts_by_date: dict[str, float],
    actuals_by_date: dict[str, float],
) -> tuple[float | None, float | None]:
    """
    Compute MAPE and RMSE over dates present in both dicts.
    MAPE excludes zero-actual days to avoid division by zero.
    """
    common_dates = set(forecasts_by_date) & set(actuals_by_date)
    if not common_dates:
        return None, None

    ape_list: list[float] = []
    sq_errors: list[float] = []
    for dt in common_dates:
        yhat = forecasts_by_date[dt]
        actual = actuals_by_date[dt]
        sq_errors.append((actual - yhat) ** 2)
        if actual > 0:
            ape_list.append(abs(actual - yhat) / actual)

    mape = float(np.mean(ape_list)) if ape_list else None
    rmse = float(np.sqrt(np.mean(sq_errors))) if sq_errors else None
    return mape, rmse


def run_forecast_eval(run_id: str, duckdb_path: str) -> ForecastEvalResult:
    """
    Load a ForecastReport and compare its predictions against actuals in fact_sales.

    For each forecasted SKU:
    - Fetches actual daily units from fact_sales AFTER as_of_date (up to horizon_days).
    - Computes MAPE and RMSE against the stored yhat values.
    - Flags SKUs where actual MAPE > 2x backtest MAPE (model was over-optimistic).

    Returns ForecastEvalResult with per-SKU accuracy and overall aggregate metrics.
    Note: If as_of_date is near the end of the dataset, few or no actuals will be
    available and per_sku entries will have n_actuals == 0.
    """
    logger.info("forecast_eval.start", run_id=run_id)
    report = _load_forecast_report(run_id, duckdb_path)

    # Build {stock_code: {date_str: yhat}} from stored forecasts
    forecasts_by_sku: dict[str, dict[str, float]] = {}
    for row in report.forecasts:
        forecasts_by_sku.setdefault(row.stock_code, {})[row.ds] = row.yhat

    # Build {stock_code: BacktestMetrics} lookup
    backtest_by_sku: dict[str, BacktestMetrics] = {
        bm.stock_code: bm for bm in report.backtest_metrics
    }

    all_codes = list(forecasts_by_sku)
    as_of_str = str(report.as_of_date)
    actuals = _fetch_actuals(all_codes, as_of_str, report.horizon_days, duckdb_path)

    per_sku: list[SKUForecastAccuracy] = []
    warnings: list[str] = []
    all_mapes: list[float] = []
    all_rmses: list[float] = []

    for code in all_codes:
        bm = backtest_by_sku.get(code)
        backtest_mape = bm.mape if bm else None
        sku_actuals = actuals.get(code, {})
        n_actuals = len(sku_actuals)

        if n_actuals == 0:
            warnings.append(
                f"SKU {code}: no actuals found beyond {as_of_str} — "
                "forecast vs actual comparison not possible."
            )
            per_sku.append(SKUForecastAccuracy(
                stock_code=code,
                forecast_horizon_days=report.horizon_days,
                backtest_mape=backtest_mape,
                actual_mape=None,
                actual_rmse=None,
                backtest_is_reliable=None,
                n_actuals=0,
            ))
            continue

        actual_mape, actual_rmse = _compute_mape_rmse(forecasts_by_sku[code], sku_actuals)

        if actual_mape is not None:
            all_mapes.append(actual_mape)
        if actual_rmse is not None:
            all_rmses.append(actual_rmse)

        # Backtest is "reliable" if actual MAPE stays within 2x the backtest MAPE
        backtest_is_reliable: bool | None = None
        if backtest_mape is not None and actual_mape is not None:
            backtest_is_reliable = actual_mape <= 2.0 * backtest_mape

        logger.info(
            "forecast_eval.sku",
            stock_code=code,
            backtest_mape=backtest_mape,
            actual_mape=actual_mape,
            n_actuals=n_actuals,
            reliable=backtest_is_reliable,
        )

        per_sku.append(SKUForecastAccuracy(
            stock_code=code,
            forecast_horizon_days=report.horizon_days,
            backtest_mape=backtest_mape,
            actual_mape=actual_mape,
            actual_rmse=actual_rmse,
            backtest_is_reliable=backtest_is_reliable,
            n_actuals=n_actuals,
        ))

    overall_mape = float(np.mean(all_mapes)) if all_mapes else None
    overall_rmse = float(np.mean(all_rmses)) if all_rmses else None

    result = ForecastEvalResult(
        run_id=run_id,
        as_of_date=as_of_str,
        model_name=report.model_name,
        total_skus_forecasted=len(all_codes),
        skus_with_actuals=sum(1 for s in per_sku if s.n_actuals > 0),
        overall_actual_mape=overall_mape,
        overall_actual_rmse=overall_rmse,
        per_sku=per_sku,
        warnings=warnings,
    )

    logger.info(
        "forecast_eval.done",
        run_id=run_id,
        overall_mape=overall_mape,
        skus_with_actuals=result.skus_with_actuals,
    )
    return result
