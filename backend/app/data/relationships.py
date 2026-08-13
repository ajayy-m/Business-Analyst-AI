"""
Lightweight foreign-key detection for multi-table datasets.

Assumes a star-schema shape: one fact table (e.g. sales) with a few
dimension tables around it (customers, products), joined on shared
ID-role columns detected by name. This is a deliberate simplification --
it won't infer a relationship if the join column has a different name in
each table -- but it covers the common case cleanly and is easy to
explain: "if two tables share a column that's an ID in at least one of
them, they're joinable on it."
"""
from app.data import catalog


def detect_relationships(dataset_id: str) -> list[dict]:
    ds = catalog.get_dataset_catalog(dataset_id)
    if not ds:
        return []

    tables = ds["tables"]
    table_names = list(tables.keys())
    relationships = []

    for i, t1 in enumerate(table_names):
        for t2 in table_names[i + 1:]:
            cols1 = {c["name"]: c for c in tables[t1]["columns"]}
            cols2 = {c["name"]: c for c in tables[t2]["columns"]}
            for col in set(cols1) & set(cols2):
                if cols1[col]["inferred_role"] == "id" or cols2[col]["inferred_role"] == "id":
                    relationships.append({"table_a": t1, "table_b": t2, "column": col})

    return relationships


def find_join_column(dataset_id: str, table_a: str, table_b: str) -> str | None:
    for rel in detect_relationships(dataset_id):
        if {rel["table_a"], rel["table_b"]} == {table_a, table_b}:
            return rel["column"]
    return None