"""
Data catalog: keeps track of what tables exist for each uploaded dataset,
their schema, and summary stats. This is what the LLM agent will read later
instead of raw data -- schema-grounded prompting instead of dumping rows.
"""
import json
import os
import duckdb
import pandas as pd
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
CATALOG_FILE = DATA_DIR / "catalog.json"


def detect_date_granularity(con, table_name: str, date_column: str) -> str:
    """
    Picks a chart/aggregation granularity for a date column from its
    actual date RANGE (min to max), not its raw timestamp spacing.
    Raw spacing would make day-level transactional data (a sale almost
    every day) detect as "day" granularity and produce an absurdly
    noisy chart with hundreds of points; bucketing by the overall span
    instead targets a sensible number of points regardless of how many
    individual rows exist within it.

    This replaces a granularity that used to be hardcoded to "quarter"
    everywhere a trend was built (Dashboard, Ask's diagnostic
    drill-down) -- which silently mislabeled annual data as quarterly
    (found on a real financial-statement upload: one row per year,
    truncated and titled "by quarter").

    Returns one of "day", "week", "month", "quarter", "year".
    """
    bounds = con.execute(
        f'SELECT min("{date_column}") AS lo, max("{date_column}") AS hi FROM "{table_name}"'
    ).fetchdf()
    if bounds.empty or pd.isna(bounds.iloc[0]["lo"]) or pd.isna(bounds.iloc[0]["hi"]):
        return "month"  # no data to measure a span from; a reasonable default

    lo, hi = bounds.iloc[0]["lo"], bounds.iloc[0]["hi"]
    span_days = (hi - lo).days

    if span_days < 14:
        return "day"
    if span_days < 90:
        return "week"
    if span_days < 730:
        return "month"
    if span_days < 365 * 8:
        return "quarter"
    return "year"


def _db_path(dataset_id: str) -> str:
    return str(DATA_DIR / f"{dataset_id}.duckdb")


def get_connection(dataset_id: str) -> duckdb.DuckDBPyConnection:
    """One DuckDB file per dataset -- keeps datasets isolated and portable."""
    return duckdb.connect(_db_path(dataset_id))


def _load_catalog() -> dict:
    if CATALOG_FILE.exists():
        with open(CATALOG_FILE) as f:
            return json.load(f)
    return {}


def _save_catalog(catalog: dict) -> None:
    with open(CATALOG_FILE, "w") as f:
        json.dump(catalog, f, indent=2, default=str)


def register_table(dataset_id: str, table_name: str, table_info: dict) -> None:
    catalog = _load_catalog()
    catalog.setdefault(dataset_id, {"tables": {}})
    catalog[dataset_id]["tables"][table_name] = table_info
    _save_catalog(catalog)


def get_dataset_catalog(dataset_id: str) -> dict | None:
    catalog = _load_catalog()
    return catalog.get(dataset_id)


def list_datasets() -> list[str]:
    catalog = _load_catalog()
    return list(catalog.keys())


def get_table_info(dataset_id: str, table_name: str) -> dict | None:
    ds = get_dataset_catalog(dataset_id)
    if not ds:
        return None
    return ds["tables"].get(table_name)


def get_column_names(dataset_id: str, table_name: str) -> list[str]:
    """Used to validate LLM-supplied column names before building SQL by
    string formatting (as detect_anomalies does) -- prevents injection
    since these values aren't going through parameterized queries."""
    info = get_table_info(dataset_id, table_name)
    if not info:
        return []
    return [c["name"] for c in info["columns"]]


def catalog_as_llm_context(dataset_id: str, table_name: str | None = None) -> str:
    """
    Renders the schema catalog as compact text for LLM grounding.
    This is what gets fed to the agent instead of raw data --
    keeps prompts small and avoids leaking full datasets into context.

    `table_name` restricts this to one table. Always pass it when the
    person has a specific dataset selected (which is now always, since
    the frontend has a single shared dataset selector): pooling every
    uploaded table's schema together, as this function used to do
    unconditionally, is precisely what let the LLM write SQL against
    the wrong table whenever two unrelated uploads happened to share a
    column name like "revenue" or "customer_id" -- there's no way for
    it to know which one you meant if it can see both.
    """
    ds = get_dataset_catalog(dataset_id)
    if not ds:
        return "No tables found for this dataset."

    tables = ds["tables"]
    if table_name is not None:
        if table_name not in tables:
            return f"Table '{table_name}' not found."
        tables = {table_name: tables[table_name]}

    lines = []
    for tname, info in tables.items():
        lines.append(f"TABLE: {tname} ({info['row_count']} rows)")
        for col in info["columns"]:
            role = f", role={col['inferred_role']}" if col.get("inferred_role") else ""
            lines.append(
                f"  - {col['name']} ({col['dtype']}{role}) "
                f"sample: {col['sample_values'][:3]}"
            )
        lines.append("")
    return "\n".join(lines)