"""
Dashboard-level anomaly scanning: proactively checks every
metric-column x category-column combination for a statistically unusual
deviation in the latest period, without the user having to ask a
specific question. This is what would power a "here's what looks off"
panel on a dashboard.

Reuses the same z-score approach as diagnostics.py, just run broadly
across the whole schema instead of one targeted drill-down.
"""
from app.data import catalog


def _zscore_series(values):
    if len(values) < 3:
        return None, None
    latest = values[-1]
    history = values[:-1]
    std = history.std()
    if std == 0:
        return None, None
    z = (latest - history.mean()) / std
    return round(float(z), 2), bool(abs(z) > 1.5)


def scan_for_anomalies(dataset_id: str, table_name: str | None = None, z_threshold: float = 1.5) -> list[dict]:
    ds = catalog.get_dataset_catalog(dataset_id)
    if not ds:
        return []

    if table_name is None:
        table_name = next(iter(ds["tables"]))
    table_info = ds["tables"][table_name]

    metric_columns = [c["name"] for c in table_info["columns"] if c["inferred_role"] == "metric"]
    category_columns = [c["name"] for c in table_info["columns"] if c["inferred_role"] == "category"]
    date_columns = [c["name"] for c in table_info["columns"] if c["inferred_role"] == "date"]

    if not metric_columns or not date_columns:
        return []
    date_column = date_columns[0]

    flags = []
    con = catalog.get_connection(dataset_id)
    try:
        for metric in metric_columns:
            # overall trend for this metric
            df = con.execute(f"""
                SELECT date_trunc('quarter', {date_column}) AS period, sum({metric}) AS value
                FROM "{table_name}" GROUP BY 1 ORDER BY 1
            """).fetchdf()
            if len(df) >= 3:
                z, notable = _zscore_series(df["value"].values)
                if notable:
                    flags.append({
                        "metric": metric,
                        "dimension": None,
                        "category": None,
                        "period": str(df["period"].iloc[-1]),
                        "value": round(float(df["value"].iloc[-1]), 2),
                        "z_score": z,
                    })

            # per-category breakdown for this metric
            for dim in category_columns:
                df_dim = con.execute(f"""
                    SELECT "{dim}" AS category, date_trunc('quarter', {date_column}) AS period,
                           sum({metric}) AS value
                    FROM "{table_name}" GROUP BY 1, 2 ORDER BY 1, 2
                """).fetchdf()
                for category_value, group in df_dim.groupby("category"):
                    group = group.sort_values("period")
                    if len(group) < 3:
                        continue
                    z, notable = _zscore_series(group["value"].values)
                    if notable and abs(z) >= z_threshold:
                        flags.append({
                            "metric": metric,
                            "dimension": dim,
                            "category": str(category_value),
                            "period": str(group["period"].iloc[-1]),
                            "value": round(float(group["value"].iloc[-1]), 2),
                            "z_score": z,
                        })
    finally:
        con.close()

    flags.sort(key=lambda f: abs(f["z_score"]), reverse=True)
    return flags