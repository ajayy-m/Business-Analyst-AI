"""
Automatic dashboard composition: the moment data is uploaded, decide
what KPI cards and charts to show -- without an LLM call and without
knowing anything about the business domain ahead of time. Same
governing principle as the rest of the app: code decides what gets
shown, a model never guesses at "good" charts.

This is really two separate problems:

  1. Chart TYPE selection -- a small deterministic rule table keyed off
     each column's inferred_role (already computed by ingestion.py) and
     its distinct_count (cardinality). See the branching in
     `compose_dashboard` below: date+metric -> trend line, low-cardinality
     category+metric -> donut, high-cardinality -> ranked top-N bar,
     id-role or text-role columns are never charted at all.

  2. Chart SELECTION -- a dataset with several metrics x several
     categories has many *valid* charts. Showing all of them isn't a
     dashboard, it's a wall. Every candidate chart is scored by how
     much the latest period deviates from history (the same z-score
     approach anomaly_dashboard.py already uses), and only the
     highest-scoring `max_charts` are returned. A dataset with no
     notable deviations anywhere still gets a baseline set of charts
     (score 0.3-0.5 floor below) rather than an empty dashboard.
"""
from app.data import catalog
from app import visualization

LOW_CARDINALITY_MAX = 6      # <= this many distinct values -> donut
HIGH_CARDINALITY_TOPN = 6    # otherwise -> ranked bar, top N + "Other"
MAX_CHARTS_DEFAULT = 8

# Deliberately NOT real geocoding -- just a name-based hint so a
# "region"/"state"/"country" column gets treated as a place-like
# dimension (preferring a ranked bar over a generic one) without
# claiming actual map support. See HANDOFF notes on this gap.
_LOCATION_COLUMN_HINTS = {
    "region", "state", "country", "city", "location", "territory", "zone", "province",
}


def _is_location_column(col_name: str) -> bool:
    lname = col_name.lower()
    return any(hint in lname for hint in _LOCATION_COLUMN_HINTS)


def _zscore(values):
    """Same z-score approach as anomaly_dashboard.py / diagnostics.py --
    latest period vs. the mean/std of everything before it."""
    if len(values) < 3:
        return None
    latest = values[-1]
    history = values[:-1]
    std = history.std()
    if std == 0:
        return None
    return round(float((latest - history.mean()) / std), 2)


def _pct_change(prev, latest):
    if prev in (0, None):
        return None
    return round(((latest - prev) / abs(prev)) * 100, 2)


def compose_dashboard(
    dataset_id: str,
    table_name: str | None = None,
    max_charts: int = MAX_CHARTS_DEFAULT,
) -> dict:
    ds = catalog.get_dataset_catalog(dataset_id)
    if not ds:
        raise ValueError("Dataset not found.")

    if table_name is None:
        table_name = next(iter(ds["tables"]))
    table_info = ds["tables"][table_name]

    metric_columns = [c["name"] for c in table_info["columns"] if c["inferred_role"] == "metric"]
    # distinct_count >= 2 excludes constant columns (nothing to break down)
    category_columns = [
        c["name"] for c in table_info["columns"]
        if c["inferred_role"] == "category" and c["distinct_count"] >= 2
    ]
    date_columns = [c["name"] for c in table_info["columns"] if c["inferred_role"] == "date"]
    cardinality = {c["name"]: c["distinct_count"] for c in table_info["columns"]}

    if not metric_columns:
        return {
            "kpis": [],
            "charts": [],
            "note": "No numeric metric columns were detected in this table, so there's nothing to chart yet.",
        }

    date_column = date_columns[0] if date_columns else None

    con = catalog.get_connection(dataset_id)
    kpis = []
    candidates = []  # list of (score, chart_dict)

    try:
        for metric in metric_columns:
            if date_column:
                df = con.execute(f"""
                    SELECT date_trunc('quarter', "{date_column}") AS period, sum("{metric}") AS value
                    FROM "{table_name}" GROUP BY 1 ORDER BY 1
                """).fetchdf()
                period_series = [
                    {"period": str(r["period"]), "value": round(float(r["value"]), 2)}
                    for _, r in df.iterrows()
                    if r["value"] == r["value"]  # drop NaN periods
                ]

                if len(df) >= 2:
                    latest = float(df["value"].iloc[-1])
                    prev = float(df["value"].iloc[-2])
                    z = _zscore(df["value"].values) if len(df) >= 3 else None
                    kpis.append({
                        "metric": metric,
                        "label": metric.replace("_", " ").title(),
                        "current_value": round(latest, 2),
                        "previous_value": round(prev, 2),
                        "pct_change": _pct_change(prev, latest),
                        "trend": "up" if latest >= prev else "down",
                        "period_label": str(df["period"].iloc[-1]),
                        "z_score": z,
                    })

                if period_series:
                    z_overall = _zscore(df["value"].values) if len(df) >= 3 else None
                    candidates.append((
                        abs(z_overall) if z_overall is not None else 0.5,  # trend always near top by default
                        {
                            "kind": "trend",
                            "metric": metric,
                            "dimension": None,
                            "spec": visualization.build_trend_chart(period_series, metric),
                        },
                    ))

            for dim in category_columns:
                n_distinct = cardinality.get(dim, 0)
                is_high_card = n_distinct > LOW_CARDINALITY_MAX

                # score this breakdown by the most anomalous category
                # within it, so a dimension with one wildly-moving
                # category still surfaces even if most are flat
                score = 0.3
                if date_column:
                    df_dim = con.execute(f"""
                        SELECT "{dim}" AS category, date_trunc('quarter', "{date_column}") AS period,
                               sum("{metric}") AS value
                        FROM "{table_name}" GROUP BY 1, 2 ORDER BY 1, 2
                    """).fetchdf()
                    best_z = None
                    for _, group in df_dim.groupby("category"):
                        group = group.sort_values("period")
                        if len(group) >= 3:
                            z = _zscore(group["value"].values)
                            if z is not None and (best_z is None or abs(z) > abs(best_z)):
                                best_z = z
                    if best_z is not None:
                        score = abs(best_z)

                if _is_location_column(dim):
                    score += 0.1  # slight preference for place-like breakdowns

                totals = con.execute(f"""
                    SELECT "{dim}" AS category, sum("{metric}") AS value
                    FROM "{table_name}"
                    WHERE "{dim}" IS NOT NULL
                    GROUP BY 1 ORDER BY 2 DESC
                """).fetchdf()
                if totals.empty:
                    continue
                rows = [
                    {"category": str(r["category"]), "value": round(float(r["value"]), 2)}
                    for _, r in totals.iterrows()
                ]

                if is_high_card:
                    top_rows = rows[:HIGH_CARDINALITY_TOPN]
                    other_total = sum(r["value"] for r in rows[HIGH_CARDINALITY_TOPN:])
                    if other_total:
                        top_rows.append({"category": "Other", "value": round(other_total, 2)})
                    spec = visualization.build_ranked_bar_chart(top_rows, metric, dim)
                    kind = "topn_bar"
                elif len(rows) <= LOW_CARDINALITY_MAX:
                    spec = visualization.build_donut_chart(rows, metric, dim)
                    kind = "donut"
                else:
                    spec = visualization.build_ranked_bar_chart(rows, metric, dim)
                    kind = "bar"

                candidates.append((score, {"kind": kind, "metric": metric, "dimension": dim, "spec": spec}))
    finally:
        con.close()

    candidates.sort(key=lambda c: c[0], reverse=True)
    charts = [c[1] for c in candidates[:max_charts]]

    return {"kpis": kpis, "charts": charts}