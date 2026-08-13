"""
Shared read-only SQL execution with a safety check. Used by both the
manual /query endpoint and the LLM-driven /ask endpoint, so there's only
one place that decides what SQL is allowed to run.
"""
import numpy as np
from app.data import catalog

FORBIDDEN_KEYWORDS = [
    "insert", "update", "delete", "drop", "alter",
    "create", "attach", "detach", "copy", "pragma", "call",
]


class UnsafeQueryError(Exception):
    pass


class QueryExecutionError(Exception):
    pass


def run_safe_query(dataset_id: str, sql: str) -> dict:
    lowered = sql.lower()
    if any(word in lowered for word in FORBIDDEN_KEYWORDS):
        raise UnsafeQueryError(
            "Query contains a disallowed keyword. Only read-only SELECT "
            "statements are permitted."
        )

    con = catalog.get_connection(dataset_id)
    try:
        result = con.execute(sql).fetchdf()
    except Exception as e:
        raise QueryExecutionError(str(e))
    finally:
        con.close()

    # SQL NULLs (e.g. the first row of a LAG() window function) become
    # NaN in pandas, which json.dumps can't serialize. Convert to None
    # so FastAPI can turn it into proper JSON null.
    result = result.replace({np.nan: None})

    return {
        "row_count": len(result),
        "columns": list(result.columns),
        "rows": result.head(200).to_dict(orient="records"),
    }