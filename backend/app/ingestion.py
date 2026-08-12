"""
Ingestion service: turns an uploaded CSV/Excel file into a queryable
DuckDB table plus catalog metadata.
"""
import re
import pandas as pd
from app import catalog


DATE_KEYWORDS = {"date", "created", "updated", "timestamp", "time"}
ID_KEYWORDS = {"id", "_id", "code", "sku", "uuid"}


def _clean_column_name(name: str) -> str:
    name = str(name).strip().lower()
    name = re.sub(r"[^a-z0-9_]+", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return name or "unnamed_col"


def _infer_role(col_name: str, series: pd.Series) -> str:
    lname = col_name.lower()
    if any(k in lname for k in DATE_KEYWORDS) or pd.api.types.is_datetime64_any_dtype(series):
        return "date"
    if any(k in lname for k in ID_KEYWORDS):
        return "id"
    if pd.api.types.is_numeric_dtype(series):
        # heuristic: low-cardinality numeric could still be categorical (e.g. a rating)
        if series.nunique() <= 10 and series.nunique() / max(len(series), 1) < 0.05:
            return "category"
        return "metric"
    if series.nunique() / max(len(series), 1) < 0.5:
        return "category"
    return "text"


def _try_parse_dates(df: pd.DataFrame) -> list[str]:
    """Attempt to parse likely date columns; return list of columns converted."""
    converted = []
    for col in df.columns:
        if pd.api.types.is_string_dtype(df[col]) or df[col].dtype == object:
            lname = col.lower()
            if any(k in lname for k in DATE_KEYWORDS):
                try:
                    parsed = pd.to_datetime(df[col], errors="coerce")
                    # only accept if most values parsed successfully
                    if parsed.notna().mean() > 0.8:
                        df[col] = parsed
                        converted.append(col)
                except Exception:
                    pass
    return converted


def parse_file(file_path: str, filename: str) -> pd.DataFrame:
    if filename.lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(file_path)
    return pd.read_csv(file_path)


def validate_dataframe(df: pd.DataFrame) -> list[str]:
    warnings = []
    if df.empty:
        warnings.append("File contains no rows.")
    dup_count = df.duplicated().sum()
    if dup_count > 0:
        warnings.append(f"{dup_count} fully duplicate rows detected.")
    high_null_cols = [
        col for col in df.columns if df[col].isna().mean() > 0.5
    ]
    if high_null_cols:
        warnings.append(f"Columns over 50% null: {', '.join(high_null_cols)}")
    return warnings


def ingest_file(dataset_id: str, table_name: str, file_path: str, filename: str) -> dict:
    df = parse_file(file_path, filename)

    # clean column names
    df.columns = [_clean_column_name(c) for c in df.columns]

    # attempt date parsing before validation/profiling
    date_cols_converted = _try_parse_dates(df)

    warnings = validate_dataframe(df)

    # profile columns for the catalog
    columns_info = []
    for col in df.columns:
        series = df[col]
        role = _infer_role(col, series)
        sample_vals = series.dropna().unique()[:5].tolist()
        columns_info.append({
            "name": col,
            "dtype": str(series.dtype),
            "inferred_role": role,
            "null_count": int(series.isna().sum()),
            "null_pct": round(float(series.isna().mean()) * 100, 2),
            "distinct_count": int(series.nunique()),
            "sample_values": [str(v) for v in sample_vals],
        })

    # load into DuckDB
    con = catalog.get_connection(dataset_id)
    con.register("df_temp", df)
    con.execute(f'CREATE OR REPLACE TABLE "{table_name}" AS SELECT * FROM df_temp')
    con.close()

    table_info = {
        "dataset_id": dataset_id,
        "table_name": table_name,
        "row_count": len(df),
        "column_count": len(df.columns),
        "columns": columns_info,
        "source_filename": filename,
        "date_columns_parsed": date_cols_converted,
    }
    catalog.register_table(dataset_id, table_name, table_info)

    return {**table_info, "warnings": warnings}
