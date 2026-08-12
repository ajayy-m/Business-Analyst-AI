"""
Data catalog: keeps track of what tables exist for each uploaded dataset,
their schema, and summary stats. This is what the LLM agent will read later
instead of raw data -- schema-grounded prompting instead of dumping rows.
"""
import json
import os
import duckdb
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
CATALOG_FILE = DATA_DIR / "catalog.json"


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


def catalog_as_llm_context(dataset_id: str) -> str:
    """
    Renders the schema catalog as compact text for LLM grounding.
    This is what gets fed to the agent instead of raw data --
    keeps prompts small and avoids leaking full datasets into context.
    """
    ds = get_dataset_catalog(dataset_id)
    if not ds:
        return "No tables found for this dataset."

    lines = []
    for table_name, info in ds["tables"].items():
        lines.append(f"TABLE: {table_name} ({info['row_count']} rows)")
        for col in info["columns"]:
            role = f", role={col['inferred_role']}" if col.get("inferred_role") else ""
            lines.append(
                f"  - {col['name']} ({col['dtype']}{role}) "
                f"sample: {col['sample_values'][:3]}"
            )
        lines.append("")
    return "\n".join(lines)
