"""
Deterministic root-cause drill-down.

Given a metric that changed between two periods, this systematically
checks every categorical dimension in the schema to find which one
explains the change, then recurses one level deeper within that
dimension (e.g. "APAC" -> "Product B within APAC"). This is the piece
that turns "revenue dropped 19.5%" into "driven by Product B in APAC."

Deliberately NOT an LLM call: contribution math and anomaly z-scores are
computed here in Python/SQL. The agent's synthesis step only narrates
these pre-computed findings -- it never does the arithmetic itself.
"""
from app.data import catalog
from app.analytics import multi_table


class DiagnosticError(Exception):
    pass


def _build_where(filters: dict):
    if not filters:
        return "", []
    clauses = [f'"{col}" = ?' for col in filters]
    return "WHERE " + " AND ".join(clauses), list(filters.values())


def _validate_columns(available_columns: list, metric_column: str, date_column: str, filters: dict):
    col_names = {c["name"]: c for c in available_columns}

    if metric_column not in col_names:
        raise DiagnosticError(f"'{metric_column}' is not a column in this dataset.")
    if col_names[metric_column]["inferred_role"] != "metric":
        raise DiagnosticError(f"'{metric_column}' is not a numeric metric column.")

    if date_column not in col_names:
        raise DiagnosticError(f"'{date_column}' is not a column in this dataset.")
    if col_names[date_column]["inferred_role"] != "date":
        raise DiagnosticError(f"'{date_column}' is not a date column.")

    for f in filters:
        if f not in col_names:
            raise DiagnosticError(f"Filter column '{f}' is not a column in this dataset.")

    return col_names


def _find_top_driver(con, table_name, metric_column, date_column, filters, dims, latest_period, prev_period, trunc):
    """Check each candidate dimension; return the one whose breakdown
    explains the largest share of the total change."""
    best = None
    for dim in dims:
        where_sql, params = _build_where(filters)
        connector = "AND" if where_sql else "WHERE"
        sql = f"""
            SELECT "{dim}" AS category, date_trunc('{trunc}', {date_column}) AS period,
                   sum({metric_column}) AS value
            FROM "{table_name}"
            {where_sql}
            {connector} date_trunc('{trunc}', {date_column}) IN (?, ?)
            GROUP BY 1, 2
        """
        df = con.execute(sql, params + [latest_period, prev_period]).fetchdf()
        if df.empty:
            continue

        pivot = df.pivot(index="category", columns="period", values="value").fillna(0)
        if latest_period not in pivot.columns or prev_period not in pivot.columns:
            continue

        pivot["delta"] = pivot[latest_period] - pivot[prev_period]
        total_delta = pivot["delta"].sum()
        if total_delta == 0:
            continue

        # "Percent of the total change" only means something when the
        # total actually changed by a non-trivial amount. When the
        # overall total barely moved (e.g. $570,191 -> $570,222, a ~$31
        # net change on a ~$570k base -- exactly what happens summing a
        # financial statement's line items across years), dividing any
        # one category's much larger delta by that near-zero total
        # explodes into a meaningless number (seen live: "1,839,426%
        # contribution"). Below a 1% relative-total-change threshold,
        # rank and report by absolute dollar movement instead -- still
        # honest, still useful, doesn't manufacture false precision out
        # of what's actually just noise around a roughly flat total.
        scale = max(abs(pivot[latest_period].sum()), abs(pivot[prev_period].sum()))
        contribution_reliable = bool(scale > 0 and abs(total_delta) / scale >= 0.01)

        if contribution_reliable:
            top_category = pivot["delta"].idxmin() if total_delta < 0 else pivot["delta"].idxmax()
            row = pivot.loc[top_category]
            contribution_pct = round(100.0 * row["delta"] / total_delta, 1)
            rank_key = abs(contribution_pct)
        else:
            top_category = pivot["delta"].abs().idxmax()
            row = pivot.loc[top_category]
            contribution_pct = None
            rank_key = abs(row["delta"])

        candidate = {
            "dimension": dim,
            "value": str(top_category),
            "value_latest": round(float(row[latest_period]), 2),
            "value_prev": round(float(row[prev_period]), 2),
            "delta": round(float(row["delta"]), 2),
            "contribution_pct": contribution_pct,
            "contribution_reliable": contribution_reliable,
            "_rank_key": rank_key,
        }
        if best is None or candidate["_rank_key"] > best["_rank_key"]:
            best = candidate
    if best is not None:
        best.pop("_rank_key", None)
    return best


def _check_anomaly(con, table_name, metric_column, date_column, filters, trunc):
    """z-score of the latest period vs the historical mean/std of this
    specific (filtered) series -- is this deviation actually unusual,
    or just normal noise?"""
    where_sql, params = _build_where(filters)
    sql = f"""
        SELECT date_trunc('{trunc}', {date_column}) AS period, sum({metric_column}) AS value
        FROM "{table_name}"
        {where_sql}
        GROUP BY 1 ORDER BY 1
    """
    df = con.execute(sql, params).fetchdf()
    if len(df) < 3:
        return {"z_score": None, "is_notable": None, "note": "Not enough history to assess."}

    values = df["value"].values
    latest = values[-1]
    history = values[:-1]
    std = history.std()
    if std == 0:
        return {"z_score": None, "is_notable": None, "note": "No variance in historical data."}

    z = (latest - history.mean()) / std
    return {"z_score": round(float(z), 2), "is_notable": bool(abs(z) > 1.0)}


def run_diagnostic(dataset_id: str, metric_column: str, date_column: str,
                    filters: dict | None = None, table_name: str | None = None) -> dict:
    filters = filters or {}
    ds = catalog.get_dataset_catalog(dataset_id)
    if not ds:
        raise DiagnosticError("Dataset not found.")

    con = catalog.get_connection(dataset_id)
    try:
        if table_name is not None:
            # Same reasoning as forecasting.forecast_metric and
            # churn.train_and_score_churn -- column names collide
            # across unrelated uploaded tables often enough that the
            # name-based auto-detect below can silently resolve to the
            # wrong one.
            if table_name not in ds["tables"]:
                raise DiagnosticError(f"Table '{table_name}' not found.")
            available_columns = ds["tables"][table_name]["columns"]
        else:
            try:
                table_name, available_columns = multi_table.resolve_base_table(
                    con, dataset_id, metric_column, date_column
                )
            except multi_table.MultiTableError as e:
                raise DiagnosticError(str(e))

        _validate_columns(available_columns, metric_column, date_column, filters)
        category_columns = [c["name"] for c in available_columns if c["inferred_role"] == "category"]

        # detect once, use everywhere below -- was hardcoded to
        # "quarter" throughout this whole function, which mislabeled
        # (and over/under-aggregated) any data whose real granularity
        # wasn't quarterly. See catalog.detect_date_granularity.
        trunc = catalog.detect_date_granularity(con, table_name, date_column)

        where_sql, params = _build_where(filters)
        periods_df = con.execute(f"""
            SELECT date_trunc('{trunc}', {date_column}) AS period, sum({metric_column}) AS value
            FROM "{table_name}"
            {where_sql}
            GROUP BY 1 ORDER BY 1
        """, params).fetchdf()

        if len(periods_df) < 2:
            raise DiagnosticError("Not enough time periods of data to compare.")

        latest_row = periods_df.iloc[-1]
        prev_row = periods_df.iloc[-2]
        pct_change = (
            round(100.0 * (latest_row["value"] - prev_row["value"]) / prev_row["value"], 1)
            if prev_row["value"] else None
        )

        overall = {
            "latest_period": str(latest_row["period"]),
            "prev_period": str(prev_row["period"]),
            "latest_value": round(float(latest_row["value"]), 2),
            "prev_value": round(float(prev_row["value"]), 2),
            "pct_change": pct_change,
            # full history, needed for trend charts -- not just the two
            # periods being compared
            "period_series": [
                {"period": str(r["period"]), "value": round(float(r["value"]), 2)}
                for _, r in periods_df.iterrows()
            ],
        }

        remaining_dims = [c for c in category_columns if c not in filters]
        level1 = _find_top_driver(
            con, table_name, metric_column, date_column, filters,
            remaining_dims, latest_row["period"], prev_row["period"], trunc,
        )

        level2 = None
        if level1:
            filters_l2 = {**filters, level1["dimension"]: level1["value"]}
            remaining_dims_l2 = [d for d in remaining_dims if d != level1["dimension"]]
            level2 = _find_top_driver(
                con, table_name, metric_column, date_column, filters_l2,
                remaining_dims_l2, latest_row["period"], prev_row["period"], trunc,
            )

        anomaly_filters = dict(filters)
        if level1:
            anomaly_filters[level1["dimension"]] = level1["value"]
        if level2:
            anomaly_filters[level2["dimension"]] = level2["value"]
        anomaly = _check_anomaly(con, table_name, metric_column, date_column, anomaly_filters, trunc)

        return {
            "metric": metric_column,
            "filters": filters,
            "granularity": trunc,
            "overall": overall,
            "level1_driver": level1,
            "level2_driver": level2,
            "anomaly": anomaly,
        }
    finally:
        con.close()