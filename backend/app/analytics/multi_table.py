"""
Resolves which table each requested column actually lives in, and --
if a question needs columns from more than one table (e.g. a metric
in 'sales' but a filter on 'segment' from 'customers') -- builds a
temp DuckDB view joining them via app.data.relationships.

This is what lets diagnostics.py and forecasting.py operate across
tables without the LLM ever having to write or even know about a JOIN.
The LLM only ever names columns; this module figures out the plumbing.
"""
from app.data import catalog, relationships


class MultiTableError(Exception):
    pass


def resolve_base_table(con, dataset_id: str, metric_column: str, date_column: str):
    """
    Returns (table_or_view_name, available_columns) that can be queried
    directly as if it were a single table.

    Always joins in every dimension table with a detected relationship to
    the fact table (not just ones referenced by an explicit filter) --
    the diagnostic drill-down needs every possible dimension available
    upfront in order to discover which one is the driver, not just the
    ones the question happened to mention.
    """
    ds = catalog.get_dataset_catalog(dataset_id)
    if not ds:
        raise MultiTableError("Dataset not found.")
    tables = ds["tables"]

    fact_table = None
    for tname, info in tables.items():
        col_names = {c["name"] for c in info["columns"]}
        if metric_column in col_names and date_column in col_names:
            fact_table = tname
            break
    if not fact_table:
        raise MultiTableError(
            f"No single table contains both '{metric_column}' and '{date_column}'."
        )

    fact_columns = tables[fact_table]["columns"]

    dim_tables = sorted({
        rel["table_b"] if rel["table_a"] == fact_table else rel["table_a"]
        for rel in relationships.detect_relationships(dataset_id)
        if fact_table in (rel["table_a"], rel["table_b"])
    })

    if not dim_tables:
        return fact_table, fact_columns

    select_parts = [f'"{fact_table}".*']
    join_clauses = []
    all_columns = list(fact_columns)
    seen_names = {c["name"] for c in fact_columns}

    for dim_table in dim_tables:
        join_col = relationships.find_join_column(dataset_id, fact_table, dim_table)
        if not join_col:
            continue
        for c in tables[dim_table]["columns"]:
            if c["name"] in seen_names:
                continue  # join column, or a name collision -- skip rather than ambiguous-duplicate
            select_parts.append(f'"{dim_table}"."{c["name"]}" AS "{c["name"]}"')
            all_columns.append(c)
            seen_names.add(c["name"])
        join_clauses.append(
            f'LEFT JOIN "{dim_table}" ON "{fact_table}"."{join_col}" = "{dim_table}"."{join_col}"'
        )

    view_name = f"_joined_{fact_table}_" + "_".join(dim_tables)
    con.execute(f"""
        CREATE OR REPLACE TEMP VIEW "{view_name}" AS
        SELECT {", ".join(select_parts)}
        FROM "{fact_table}"
        {" ".join(join_clauses)}
    """)

    return view_name, all_columns