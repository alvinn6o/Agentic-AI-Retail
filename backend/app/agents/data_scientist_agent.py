"""DataScientistAgent — demand forecasting with backtest metrics.

Model selection (per SKU):
  1. LightGBM  — series with >= 56 days and >= 14 non-zero days
                  features: calendar + lag_7/14/28 + rolling mean/std
                  backtest: real 28-day holdout (not in-sample)
                  uncertainty: training residual 10th/90th percentiles
  2. Seasonal Naive (improved) — fallback for short/sparse series
                  forecast: 4-week same-DOW rolling average
                  gap fill: forward-fill then zero (not pure zero)
                  uncertainty: ±1.5 * same-DOW std over last 8 weeks
"""

from __future__ import annotations

import warnings
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from backend.app.core.config import Settings, get_settings
from backend.app.core.logging import get_logger
from backend.app.models.reports import BacktestMetrics, ForecastReport, ForecastRow, QueryEvidence
from backend.app.models.run_context import RunContext
from backend.app.tools.sql_tool import SQLTool

logger = get_logger(__name__)
warnings.filterwarnings("ignore")

# ─── LightGBM constants ───────────────────────────────────────────────────────

_LGBM_FEATURES = [
    "day_of_week",
    "week_of_year",
    "month",
    "lag_7",
    "lag_14",
    "lag_28",
    "rolling_mean_7",
    "rolling_mean_14",
    "rolling_std_7",
]

_LGBM_MIN_DAYS = 56        # minimum training days for LightGBM
_LGBM_MIN_NONZERO = 14     # minimum non-zero demand days
_HOLDOUT_DAYS = 28         # real held-out test window


# ─── Improved Seasonal Naive (Option A) ───────────────────────────────────────

def _fill_series(raw: pd.Series) -> pd.Series:
    """
    Fill missing days properly:
      1. Forward-fill gaps up to 6 days (carry last known demand).
      2. Zero-fill any remaining gaps at the start of the series.
    Pure zero-fill was distorting rolling averages and degrading forecasts.
    """
    filled = raw.ffill(limit=6).fillna(0.0)
    return filled


def _same_dow_values(series: pd.Series, target: date, n_weeks: int = 8) -> list[float]:
    """Return up to n_weeks of historical values for the same day-of-week as target."""
    vals = []
    for w in range(1, n_weeks + 1):
        lag_date = target - timedelta(days=7 * w)
        lag_str = lag_date.strftime("%Y-%m-%d")
        if lag_str in series.index:
            vals.append(float(series[lag_str]))
    return vals


def _compute_naive_forecast(
    series: pd.Series,
    horizon_days: int,
    as_of_date: date,
) -> list[dict[str, Any]]:
    """
    Improved seasonal naive forecast.

    For each forecast day:
      - Collect same-day-of-week values from the last 4 training weeks
        (weighted: more recent weeks count 2x).
      - Point forecast = weighted average.
      - Bands = point ± 1.5 * std of those same-DOW values (minimum ±0.5 units).
    """
    forecasts = []
    for i in range(1, horizon_days + 1):
        target = as_of_date + timedelta(days=i)
        vals = _same_dow_values(series, target, n_weeks=4)

        if not vals:
            # Nothing in training window — fall back to overall mean
            yhat = float(series[series > 0].mean()) if (series > 0).any() else 0.0
            std = float(series.std()) if len(series) > 1 else 1.0
        else:
            # Weight more recent weeks more heavily (2,2,1,1 for 4 weeks)
            weights = [2.0, 2.0, 1.0, 1.0][: len(vals)]
            yhat = float(np.average(vals, weights=weights))
            std = float(np.std(vals)) if len(vals) > 1 else abs(yhat) * 0.2

        half_band = max(1.5 * std, 0.5)
        forecasts.append({
            "ds": target.strftime("%Y-%m-%d"),
            "yhat": round(max(yhat, 0), 2),
            "yhat_lower": round(max(yhat - half_band, 0), 2),
            "yhat_upper": round(max(yhat + half_band, 0), 2),
        })
    return forecasts


def _compute_backtest_naive(series: pd.Series, holdout_days: int = _HOLDOUT_DAYS) -> dict[str, Any]:
    """
    Real holdout backtest for seasonal naive:
      - Hold out last holdout_days days.
      - Predict each held-out day using same-DOW values from BEFORE the holdout.
    """
    if len(series) < holdout_days + 14:
        return {"mape": None, "rmse": None}

    train = series.iloc[:-holdout_days]
    test = series.iloc[-holdout_days:]

    errors, sq_errors = [], []
    as_of = date.fromisoformat(train.index[-1])

    for i, (dt_str, actual) in enumerate(test.items()):
        target = date.fromisoformat(dt_str)
        vals = _same_dow_values(train, target, n_weeks=4)
        if not vals:
            pred = float(train[train > 0].mean()) if (train > 0).any() else 0.0
        else:
            weights = [2.0, 2.0, 1.0, 1.0][: len(vals)]
            pred = float(np.average(vals, weights=weights))

        pred = max(pred, 0)
        if actual > 0:
            errors.append(abs(actual - pred) / actual)
        sq_errors.append((actual - pred) ** 2)

    mape = float(np.mean(errors)) if errors else None
    rmse = float(np.sqrt(np.mean(sq_errors))) if sq_errors else None
    return {"mape": mape, "rmse": rmse}


# ─── LightGBM (Option B) ──────────────────────────────────────────────────────

def _build_features(series: pd.Series) -> pd.DataFrame:
    """Build a feature matrix from a daily demand series with string index."""
    df = pd.DataFrame({"y": series.values}, index=pd.to_datetime(series.index))
    df["day_of_week"] = df.index.dayofweek
    df["week_of_year"] = df.index.isocalendar().week.astype(int)
    df["month"] = df.index.month
    # Lag features — shift so they use values known before the target day
    df["lag_7"] = df["y"].shift(7)
    df["lag_14"] = df["y"].shift(14)
    df["lag_28"] = df["y"].shift(28)
    # Rolling features — shift(1) so the target day is not included
    df["rolling_mean_7"] = df["y"].shift(1).rolling(7, min_periods=3).mean()
    df["rolling_mean_14"] = df["y"].shift(1).rolling(14, min_periods=7).mean()
    df["rolling_std_7"] = df["y"].shift(1).rolling(7, min_periods=3).std().fillna(0.0)
    return df.dropna(subset=_LGBM_FEATURES)


def _lgbm_recursive_forecast(
    model: Any,
    series: pd.Series,
    horizon_days: int,
    as_of_date: date,
    residual_std: float,
) -> list[dict[str, Any]]:
    """
    Recursive multi-step forecast:
      - For each future day, build lag features from the series
        (which grows as we append each day's prediction).
      - Uncertainty = ±1.28 * residual_std (≈ 80% prediction interval).
    """
    # Work on a float series with date-string index
    extended = series.copy().astype(float)

    rows = []
    for i in range(1, horizon_days + 1):
        target = pd.Timestamp(as_of_date) + pd.Timedelta(days=i)
        t_str = target.strftime("%Y-%m-%d")

        feats: dict[str, float] = {
            "day_of_week": float(target.dayofweek),
            "week_of_year": float(target.isocalendar()[1]),
            "month": float(target.month),
        }

        def _get(lag: int) -> float:
            lag_str = (target - pd.Timedelta(days=lag)).strftime("%Y-%m-%d")
            return float(extended.get(lag_str, extended.mean()))

        feats["lag_7"] = _get(7)
        feats["lag_14"] = _get(14)
        feats["lag_28"] = _get(28)

        recent7 = extended.iloc[-7:] if len(extended) >= 7 else extended
        recent14 = extended.iloc[-14:] if len(extended) >= 14 else extended
        feats["rolling_mean_7"] = float(recent7.mean())
        feats["rolling_mean_14"] = float(recent14.mean())
        feats["rolling_std_7"] = float(recent7.std()) if len(recent7) > 1 else 0.0

        X = pd.DataFrame([feats])[_LGBM_FEATURES]
        yhat = float(max(model.predict(X)[0], 0))

        half_band = max(1.28 * residual_std, 0.5)
        rows.append({
            "ds": t_str,
            "yhat": round(yhat, 2),
            "yhat_lower": round(max(yhat - half_band, 0), 2),
            "yhat_upper": round(yhat + half_band, 2),
        })
        # Append prediction so future lags can reference it
        extended[t_str] = yhat

    return rows


def _fit_lgbm(
    series: pd.Series,
    horizon_days: int,
    as_of_date: date,
) -> tuple[list[dict[str, Any]], dict[str, Any], str] | None:
    """
    Fit LightGBM on all-but-last-28 days; evaluate on real 28-day holdout.
    Returns (forecast_rows, metrics, model_name) or None if fitting fails.
    """
    try:
        import lightgbm as lgb
    except ImportError:
        logger.warning("data_scientist.lgbm_not_installed")
        return None

    df = _build_features(series)
    if len(df) < _HOLDOUT_DAYS + 14:
        return None

    train_df = df.iloc[:-_HOLDOUT_DAYS]
    test_df = df.iloc[-_HOLDOUT_DAYS:]

    X_train, y_train = train_df[_LGBM_FEATURES], train_df["y"]
    X_test, y_test = test_df[_LGBM_FEATURES], test_df["y"]

    try:
        model = lgb.LGBMRegressor(
            n_estimators=300,
            learning_rate=0.05,
            num_leaves=15,        # small — prevents overfitting on short series
            min_child_samples=5,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            verbose=-1,
        )
        model.fit(X_train, y_train)
    except Exception as exc:
        logger.warning("data_scientist.lgbm_fit_failed", error=str(exc))
        return None

    # Real holdout evaluation
    preds = np.maximum(model.predict(X_test), 0)
    mask_nonzero = y_test > 0
    mape = float(np.mean(np.abs(y_test[mask_nonzero] - preds[mask_nonzero]) / y_test[mask_nonzero])) if mask_nonzero.any() else None
    rmse = float(np.sqrt(np.mean((y_test - preds) ** 2)))

    # Residual std from training set for uncertainty bands
    train_preds = np.maximum(model.predict(X_train), 0)
    residual_std = float(np.std(y_train - train_preds))

    # Recursive forward forecast
    rows = _lgbm_recursive_forecast(model, series, horizon_days, as_of_date, residual_std)
    metrics = {"mape": mape, "rmse": rmse}
    return rows, metrics, "lightgbm"


# ─── Agent ────────────────────────────────────────────────────────────────────

class DataScientistAgent:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def run(self, ctx: RunContext, horizon_days: int = 28) -> ForecastReport:
        logger.info("data_scientist.start", run_id=ctx.run_id)

        sql = SQLTool(ctx.as_of_date, ctx.mode, self.settings)
        queries_executed: list[QueryEvidence] = []

        # Top 20 SKUs by revenue
        top_rows, ev = sql.run(
            """
            SELECT stock_code, SUM(revenue) AS total_revenue
            FROM fact_sales
            GROUP BY stock_code
            ORDER BY total_revenue DESC
            LIMIT 20
            """,
            step="top_skus_for_forecast",
        )
        queries_executed.append(ev)

        # Deduplicate while preserving revenue-rank order
        seen: set[str] = set()
        top_codes: list[str] = []
        for r in top_rows:
            c = r["stock_code"]
            if c not in seen:
                seen.add(c)
                top_codes.append(c)
        codes_placeholder = ", ".join(f"'{c}'" for c in top_codes)

        # Daily demand for top SKUs (returns excluded)
        demand_rows, dem_ev = sql.run(
            f"""
            SELECT
                stock_code,
                CAST(invoice_date AS DATE) AS sale_date,
                SUM(quantity)              AS daily_units
            FROM fact_sales
            WHERE stock_code IN ({codes_placeholder})
              AND quantity > 0
            GROUP BY stock_code, CAST(invoice_date AS DATE)
            ORDER BY stock_code, sale_date
            """,
            step="daily_demand",
        )
        queries_executed.append(dem_ev)

        forecasts: list[ForecastRow] = []
        backtest_metrics: list[BacktestMetrics] = []
        model_names_used: list[str] = []

        demand_df = pd.DataFrame(demand_rows)

        for code in top_codes[:5]:
            sku_df = demand_df[demand_df["stock_code"] == code].copy()
            if len(sku_df) < 14:
                logger.info("data_scientist.skip_short_series", stock_code=code, rows=len(sku_df))
                continue

            sku_df["sale_date"] = pd.to_datetime(sku_df["sale_date"])
            raw_series = sku_df.set_index("sale_date")["daily_units"].astype(float)

            # Full date range, then improved fill (forward-fill gaps ≤6 days, then zero)
            idx = pd.date_range(raw_series.index.min(), ctx.as_of_date)
            raw_series = raw_series.reindex(idx)
            series = _fill_series(raw_series)
            series.index = series.index.strftime("%Y-%m-%d")

            train_start = series.index[0]
            train_end = series.index[-1]
            nonzero_days = int((series > 0).sum())

            logger.info(
                "data_scientist.sku",
                stock_code=code,
                total_days=len(series),
                nonzero_days=nonzero_days,
            )

            # Model selection: LightGBM first, naive fallback
            result = None
            if len(series) >= _LGBM_MIN_DAYS and nonzero_days >= _LGBM_MIN_NONZERO:
                try:
                    result = _fit_lgbm(series, horizon_days, ctx.as_of_date)
                except Exception as exc:
                    logger.error("data_scientist.lgbm_exception", stock_code=code, error=str(exc))
                    result = None

            logger.info(
                "data_scientist.model_choice",
                stock_code=code,
                selected="lightgbm" if result is not None else "seasonal_naive",
                series_len=len(series),
                nonzero_days=nonzero_days,
            )

            if result is not None:
                rows, metrics, model_name = result
            else:
                rows = _compute_naive_forecast(series, horizon_days, ctx.as_of_date)
                metrics = _compute_backtest_naive(series)
                model_name = "seasonal_naive"

            model_names_used.append(model_name)
            logger.info("data_scientist.model_selected", stock_code=code, model=model_name,
                        mape=metrics.get("mape"), rmse=metrics.get("rmse"))

            for row in rows:
                forecasts.append(ForecastRow(stock_code=code, **row))

            backtest_metrics.append(BacktestMetrics(
                stock_code=code,
                mape=metrics.get("mape"),
                rmse=metrics.get("rmse"),
                train_start=str(train_start),
                train_end=str(train_end),
                horizon_days=horizon_days,
            ))

        # Report the dominant model used
        dominant_model = (
            "lightgbm"
            if model_names_used.count("lightgbm") >= len(model_names_used) / 2
            else "seasonal_naive"
        )

        report = ForecastReport(
            run_id=ctx.run_id,
            as_of_date=ctx.as_of_date,
            mode=ctx.mode,
            model_name=dominant_model,
            horizon_days=horizon_days,
            train_window_days=int(len(demand_df) / max(len(top_codes[:5]), 1)),
            forecasts=forecasts,
            backtest_metrics=backtest_metrics,
            assumptions=[
                "Missing days forward-filled (up to 6 consecutive days), remainder zero-filled",
                "Negative quantity (returns) excluded from training data",
                f"Top 5 SKUs by revenue forecasted as of {ctx.as_of_date}",
                f"LightGBM: 28-day real holdout backtest; uncertainty = +/-1.28 * training residual std",
                f"Seasonal naive: 4-week same-DOW weighted average; uncertainty = +/-1.5 * same-DOW std",
            ],
            queries_executed=queries_executed,
        )

        logger.info("data_scientist.done", run_id=ctx.run_id,
                    num_forecasts=len(forecasts), model=dominant_model)
        return report
