"""
Forecasting -- projects a metric forward using a linear trend fit to
historical periods, with a confidence band from the residual spread.

Deliberately simple (not Prophet/ARIMA): with only a handful of periods
of data (a few quarters or months), a linear trend is honest about what
the data actually supports, and every number is traceable to a formula
you can explain in an interview, rather than a black-box library call.
"""
import numpy as np
from app.data import catalog
from app.analytics import multi_table


class ForecastError(Exception):
    pass


def _period_trunc_sql(granularity: str) -> str:
    if granularity not in ("day", "week", "month", "quarter", "year"):
        raise ForecastError(f"Unsupported granularity: {granularity}")
    return granularity


def forecast_metric(
    dataset_id: str,
    metric_column: str,
    date_column: str,
    filters: dict | None = None,
    periods_ahead: int = 3,
    granularity: str = "month",
) -> dict:
    filters = filters or {}
    ds = catalog.get_dataset_catalog(dataset_id)
    if not ds:
        raise ForecastError("Dataset not found.")

    trunc = _period_trunc_sql(granularity)

    con = catalog.get_connection(dataset_id)
    try:
        try:
            table_name, available_columns = multi_table.resolve_base_table(
                con, dataset_id, metric_column, date_column
            )
        except multi_table.MultiTableError as e:
            raise ForecastError(str(e))

        col_names = {c["name"]: c for c in available_columns}
        if metric_column not in col_names or col_names[metric_column]["inferred_role"] != "metric":
            raise ForecastError(f"'{metric_column}' is not a valid metric column.")
        if date_column not in col_names or col_names[date_column]["inferred_role"] != "date":
            raise ForecastError(f"'{date_column}' is not a valid date column.")
        for f in filters:
            if f not in col_names:
                raise ForecastError(f"Filter column '{f}' not found in schema.")

        where_clauses = [f'"{col}" = ?' for col in filters]
        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        df = con.execute(f"""
            SELECT date_trunc('{trunc}', {date_column}) AS period, sum({metric_column}) AS value
            FROM "{table_name}"
            {where_sql}
            GROUP BY 1 ORDER BY 1
        """, list(filters.values())).fetchdf()
    finally:
        con.close()

    if len(df) < 3:
        raise ForecastError(
            f"Not enough historical periods ({len(df)}) at '{granularity}' "
            "granularity to fit a trend. Try a finer granularity (e.g. 'month')."
        )

    x = np.arange(len(df))
    y = df["value"].values

    # simple linear trend: y = slope*x + intercept
    slope, intercept = np.polyfit(x, y, 1)
    fitted = slope * x + intercept
    residuals = y - fitted
    residual_std = residuals.std(ddof=2) if len(df) > 2 else residuals.std()

    future_x = np.arange(len(df), len(df) + periods_ahead)
    future_values = slope * future_x + intercept

    # naive prediction interval: widens with distance from the observed
    # data, using the residual spread as the noise estimate
    z_95 = 1.96
    future_margins = z_95 * residual_std * np.sqrt(1 + (future_x - x.mean()) ** 2 / ((x - x.mean()) ** 2).sum() + 1 / len(x))

    last_period = df["period"].iloc[-1]
    future_periods = _project_periods(last_period, periods_ahead, granularity)

    history = [
        {"period": str(p), "value": round(float(v), 2)}
        for p, v in zip(df["period"], df["value"])
    ]
    forecast = [
        {
            "period": str(p),
            "value": round(float(v), 2),
            "lower": round(float(v - m), 2),
            "upper": round(float(v + m), 2),
        }
        for p, v, m in zip(future_periods, future_values, future_margins)
    ]

    trend_direction = "increasing" if slope > 0 else ("decreasing" if slope < 0 else "flat")
    # rough trend strength: R^2 of the linear fit
    ss_res = (residuals ** 2).sum()
    ss_tot = ((y - y.mean()) ** 2).sum()
    r_squared = round(float(1 - ss_res / ss_tot), 3) if ss_tot > 0 else None

    return {
        "metric": metric_column,
        "granularity": granularity,
        "filters": filters,
        "history": history,
        "forecast": forecast,
        "trend": {
            "direction": trend_direction,
            "slope_per_period": round(float(slope), 2),
            "r_squared": r_squared,
        },
    }


def _project_periods(last_period, count: int, granularity: str) -> list:
    """Generate the next `count` period start dates after last_period."""
    import pandas as pd
    offset_map = {
        "day": pd.DateOffset(days=1),
        "week": pd.DateOffset(weeks=1),
        "month": pd.DateOffset(months=1),
        "quarter": pd.DateOffset(months=3),
        "year": pd.DateOffset(years=1),
    }
    offset = offset_map[granularity]
    periods = []
    current = pd.Timestamp(last_period)
    for _ in range(count):
        current = current + offset
        periods.append(current)
    return periods