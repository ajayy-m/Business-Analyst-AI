"""
Ingestion service: turns an uploaded CSV/Excel file into a queryable
DuckDB table plus catalog metadata.

Hardened against common messy-real-world-export patterns (see
HANDOFF_v2.md section 6 for the stress-test writeup that motivated
this pass):
  - a title row sitting above the real header row (manual Excel exports)
  - currency symbols / thousands separators in numeric columns
  - percent signs in numeric columns
  - accounting-style parenthesis negatives, e.g. "(123.45)"
  - leading/trailing whitespace in header AND value cells
  - fully blank rows
  - ID columns that would otherwise get silently re-typed as numbers,
    destroying leading zeros (e.g. "00123" -> 123)
  - date columns with inconsistent formats: previously these were still
    labeled role="date" even when parsing failed and the column stayed
    text, which crashed the dashboard/forecast SQL (date_trunc on a
    VARCHAR). Role is now only ever "date" when the column actually
    parsed to a real datetime dtype.

Deliberately NOT attempted here: fuzzy category normalization (e.g.
merging "USA" / "U.S.A." / "United States"). That needs a lookup table
or LLM judgment call, not a safe automatic rule -- documented as a
known limitation rather than silently "fixed" in a way that could merge
things that shouldn't be merged.
"""
import re
from collections import Counter

import pandas as pd
from app.data import catalog


DATE_KEYWORDS = {"date", "created", "updated", "timestamp", "time"}
ID_KEYWORDS = {"id", "_id", "code", "sku", "uuid"}

_CURRENCY_CHARS_RE = re.compile(r"[$£€,]")
_PAREN_NEGATIVE_RE = re.compile(r"^\((.*)\)$")
_NULLISH_STRINGS = {"", "nan", "none", "null", "n/a", "na", "-"}

_HEADER_SCAN_MAX_ROWS = 15
_RAGGED_ROW_PEEK_WIDTH = 1000


def _clean_column_name(name: str) -> str:
    name = str(name).strip().lower()
    name = re.sub(r"[^a-z0-9_]+", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return name or "unnamed_col"


def _is_blank_cell(v) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and pd.isna(v):
        return True
    return str(v).strip() == ""


def _count_nonempty(row) -> int:
    return sum(1 for c in row if not _is_blank_cell(c))


def _read_raw_rows(file_path: str, filename: str, max_scan: int = _HEADER_SCAN_MAX_ROWS) -> list:
    """Peek at the first few raw rows (no header assumed) so we can
    detect whether row 0 is a real header or a title/banner row.

    Deliberately uses pandas' own row-numbering convention (which
    defaults to skip_blank_lines=True) rather than a raw csv.reader.
    csv.reader counts every physical line including blank ones, but
    pandas' `header=N` parameter counts rows *after* blank lines are
    dropped -- so a raw csv.reader scan and the real pd.read_csv(header=N)
    call disagree on what row N means whenever a blank line sits above
    the header (e.g. a title row followed by a blank spacer row before
    the real header), silently pointing the header detection at the
    wrong row. Reading the peek with pandas itself keeps the indices
    consistent with the real read that follows."""
    if filename.lower().endswith((".xlsx", ".xls")):
        raw = pd.read_excel(file_path, header=None, nrows=max_scan)
        return raw.values.tolist()
    # A title row has far fewer fields than the real header/data rows
    # (e.g. one free-text cell vs. eight columns), so a plain
    # header=None read would infer its column count from row 0 and then
    # error out ("Expected 1 fields, saw 8") once it hits a wider row.
    # Pinning a generous fixed column count sidesteps that: pandas pads
    # every row to the same width with NaN instead of validating it.
    raw = pd.read_csv(
        file_path, header=None, nrows=max_scan, dtype=str,
        names=range(_RAGGED_ROW_PEEK_WIDTH),
        skip_blank_lines=True, keep_default_na=True,
    )
    return raw.values.tolist()


def _detect_header_row(rows: list) -> int:
    """
    Finds the most likely header row index. Handles the common manual-
    export pattern of a single-cell title row (and maybe a blank row)
    sitting above the real header: a title row has very few non-empty
    cells compared to the header/data rows below it, so we look for the
    first row whose non-empty cell count is close to the "typical" row
    width rather than blindly trusting row 0.
    """
    if not rows:
        return 0
    counts = [_count_nonempty(r) for r in rows]
    candidates = [c for c in counts if c > 1]
    if not candidates:
        return 0
    mode_count = Counter(candidates).most_common(1)[0][0]
    threshold = max(2, int(mode_count * 0.7))
    for i, c in enumerate(counts):
        if c >= threshold:
            return i
    return 0


def parse_file(file_path: str, filename: str) -> tuple[pd.DataFrame, int]:
    """Returns (dataframe, header_row_index_used). Everything is read as
    string first -- numeric/date typing happens explicitly afterwards so
    we control exactly how currency symbols, percents, parens, and
    leading-zero IDs are handled, instead of leaving it to pandas'
    automatic dtype inference."""
    header_row = _detect_header_row(_read_raw_rows(file_path, filename))
    if filename.lower().endswith((".xlsx", ".xls")):
        df = pd.read_excel(file_path, header=header_row, dtype=str)
    else:
        df = pd.read_csv(file_path, header=header_row, dtype=str, keep_default_na=True)
    return df, header_row


def _strip_whitespace_values(df: pd.DataFrame) -> None:
    """In-place: trims leading/trailing whitespace from every string
    cell. Column-name whitespace is already handled by
    _clean_column_name; this covers the value-level case (e.g.
    " Gamma Inc" vs "Gamma Inc" silently fragmenting a category)."""
    for col in df.columns:
        df[col] = df[col].apply(lambda v: v.strip() if isinstance(v, str) else v)


def _drop_blank_rows(df: pd.DataFrame) -> int:
    """In-place-ish: returns a new-index df with fully-blank rows
    removed, and the count removed (common in manual Excel exports as
    spacer rows)."""
    blank_mask = df.apply(lambda row: all(_is_blank_cell(v) for v in row), axis=1)
    return int(blank_mask.sum())


def _try_parse_dates(df: pd.DataFrame) -> tuple[list[str], list[str]]:
    """Attempt to parse likely date columns (by name). Returns
    (converted, attempted_but_failed) so callers can warn about the
    latter instead of silently mislabeling a text column as a date."""
    converted = []
    attempted_but_failed = []
    for col in df.columns:
        lname = col.lower()
        if not any(k in lname for k in DATE_KEYWORDS):
            continue
        try:
            parsed = pd.to_datetime(df[col], errors="coerce")
        except Exception:
            attempted_but_failed.append(col)
            continue
        # only accept if most values parsed successfully -- a column
        # with genuinely mixed/inconsistent date formats should stay
        # text rather than silently losing half its rows to NaT.
        non_null_original = df[col].notna().sum()
        if non_null_original > 0 and (parsed.notna().sum() / non_null_original) > 0.8:
            df[col] = parsed
            converted.append(col)
        else:
            attempted_but_failed.append(col)
    return converted, attempted_but_failed


def _clean_numeric_value(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip()
    if s.lower() in _NULLISH_STRINGS:
        return None
    negative = False
    m = _PAREN_NEGATIVE_RE.match(s)
    if m:
        negative = True
        s = m.group(1).strip()
    s = s.replace("%", "")
    s = _CURRENCY_CHARS_RE.sub("", s)
    s = s.strip()
    if s == "":
        return None
    try:
        val = float(s)
    except ValueError:
        return None
    return -val if negative else val


def _try_clean_numeric_column(series: pd.Series) -> pd.Series | None:
    """Attempts to coerce a text column into numbers by stripping
    currency symbols, thousands separators, percent signs, and
    accounting-style parenthesis negatives. Only accepted if the large
    majority of non-null values convert cleanly -- a genuinely
    non-numeric text column should be left alone."""
    non_null_original = series.notna().sum()
    if non_null_original == 0:
        return None
    cleaned = series.apply(_clean_numeric_value)
    if (cleaned.notna().sum() / non_null_original) >= 0.8:
        return cleaned
    return None


def _infer_role(col_name: str, series: pd.Series, is_parsed_date: bool = False) -> str:
    lname = col_name.lower()
    # "date" is only ever assigned when the column actually parsed to a
    # real datetime dtype -- a column that merely has a date-ish name
    # but failed to parse (inconsistent formats etc.) must NOT get this
    # role, since downstream SQL (date_trunc, forecasting) trusts the
    # role and will crash against a VARCHAR column.
    if is_parsed_date or pd.api.types.is_datetime64_any_dtype(series):
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


def validate_dataframe(df: pd.DataFrame) -> dict:
    """Computes data-quality signals once, structured -- used both for
    the plain-English warnings list and the Data Quality Summary panel,
    so the two can never drift out of sync with each other."""
    dup_count = int(df.duplicated().sum())
    high_null_cols = [col for col in df.columns if df[col].isna().mean() > 0.5]

    warnings = []
    if df.empty:
        warnings.append("File contains no rows.")
    if dup_count > 0:
        warnings.append(f"{dup_count} fully duplicate rows detected.")
    if high_null_cols:
        warnings.append(f"Columns over 50% null: {', '.join(high_null_cols)}")

    return {
        "warnings": warnings,
        "duplicate_row_count": dup_count,
        "high_null_columns": high_null_cols,
    }


def ingest_file(dataset_id: str, table_name: str, file_path: str, filename: str) -> dict:
    df, header_row = parse_file(file_path, filename)

    # clean column names
    df.columns = [_clean_column_name(c) for c in df.columns]

    warnings = []
    if header_row > 0:
        warnings.append(
            f"Detected {header_row} row(s) above the real header (e.g. a title "
            f"row) and skipped them."
        )

    # value-level whitespace, then drop spacer/blank rows, before any
    # typing decisions are made
    _strip_whitespace_values(df)
    blank_rows_dropped = _drop_blank_rows(df)
    if blank_rows_dropped:
        df = df[~df.apply(lambda row: all(_is_blank_cell(v) for v in row), axis=1)].reset_index(drop=True)
        warnings.append(f"{blank_rows_dropped} fully blank row(s) removed.")

    # attempt date parsing before numeric cleaning / profiling
    date_cols_converted, date_cols_failed = _try_parse_dates(df)
    for col in date_cols_failed:
        warnings.append(
            f"Column '{col}' looks like a date but has inconsistent or "
            f"unparseable formats -- kept as text rather than guessing."
        )

    # attempt numeric cleaning (currency symbols, %, thousands separators,
    # accounting negatives) on everything that isn't an ID column (IDs are
    # kept as raw strings so leading zeros like "00123" survive) or an
    # already-converted date column
    numeric_cols_cleaned = []
    for col in df.columns:
        lname = col.lower()
        if any(k in lname for k in ID_KEYWORDS):
            continue
        if col in date_cols_converted:
            continue
        # Every remaining column was read with dtype=str (see parse_file),
        # so it's still text at this point -- but which text dtype that
        # actually is depends on the pandas version: older pandas gives
        # plain numpy `object`, pandas 3.x's dtype=str gives its own
        # StringDtype, which fails a strict `== object` check. Checking
        # via pandas' own dtype-kind helper instead of a hardcoded numpy
        # object comparison keeps this correct across both.
        if not (
            pd.api.types.is_object_dtype(df[col])
            or pd.api.types.is_string_dtype(df[col])
        ):
            continue
        cleaned = _try_clean_numeric_column(df[col])
        if cleaned is not None:
            df[col] = cleaned
            numeric_cols_cleaned.append(col)

    dq = validate_dataframe(df)
    warnings.extend(dq["warnings"])

    # profile columns for the catalog
    columns_info = []
    for col in df.columns:
        series = df[col]
        role = _infer_role(col, series, is_parsed_date=col in date_cols_converted)
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

    total_cells = len(df) * len(df.columns)
    missing_value_count = sum(c["null_count"] for c in columns_info)
    missing_cell_pct = (missing_value_count / total_cells) if total_cells else 0.0
    duplicate_row_pct = (dq["duplicate_row_count"] / len(df)) if len(df) else 0.0

    # A plain, explainable formula -- not a black-box score -- consistent
    # with this whole app's "every number traceable" principle: start at
    # 100, subtract for the three concrete problems this panel reports,
    # each capped so one bad column/table doesn't single-handedly zero
    # out an otherwise-fine dataset.
    quality_score = 100.0
    quality_score -= min(40.0, missing_cell_pct * 100)
    quality_score -= min(30.0, duplicate_row_pct * 100)
    quality_score -= 10.0 * len(date_cols_failed)
    quality_score = round(max(0.0, quality_score))

    data_quality = {
        "row_count": len(df),
        "column_count": len(df.columns),
        "missing_value_count": missing_value_count,
        "missing_cell_pct": round(missing_cell_pct * 100, 2),
        "duplicate_row_count": dq["duplicate_row_count"],
        "invalid_date_columns": date_cols_failed,
        "high_null_columns": dq["high_null_columns"],
        "header_rows_skipped": header_row,
        "blank_rows_dropped": blank_rows_dropped,
        "numeric_columns_cleaned": numeric_cols_cleaned,
        "quality_score": quality_score,
        "warnings": warnings,
    }

    table_info = {
        "dataset_id": dataset_id,
        "table_name": table_name,
        "row_count": len(df),
        "column_count": len(df.columns),
        "columns": columns_info,
        "source_filename": filename,
        "date_columns_parsed": date_cols_converted,
        "numeric_columns_cleaned": numeric_cols_cleaned,
        "header_rows_skipped": header_row,
        "blank_rows_dropped": blank_rows_dropped,
        # Previously computed but never persisted -- only ever returned
        # once in the upload response and then lost, so a Data Quality
        # panel would go blank on every visit after the first. Now part
        # of the saved catalog record, retrievable any time via
        # GET /datasets/{id}/catalog, same as every other column stat.
        "data_quality": data_quality,
    }
    catalog.register_table(dataset_id, table_name, table_info)

    return {**table_info, "warnings": warnings}

# ---------------------------------------------------------------------------
# Manual column-role override
# ---------------------------------------------------------------------------

VALID_ROLES = {"date", "metric", "category", "id", "text"}
_MIN_PARSE_SUCCESS = 0.8  # same bar ingestion applies to dates and numerics


class ColumnOverrideError(Exception):
    """Raised when a requested role override can't be honored. The message
    is user-facing and always states the actual measured reason."""


def _compute_quality_score(missing_cell_pct: float, duplicate_row_pct: float, invalid_date_cols: int) -> int:
    """Same formula ingest_file uses (kept in one place for overrides)."""
    score = 100.0
    score -= min(40.0, missing_cell_pct * 100)
    score -= min(30.0, duplicate_row_pct * 100)
    score -= 10.0 * invalid_date_cols
    return int(round(max(0.0, score)))


def _profile_column(name: str, series: pd.Series, role: str) -> dict:
    sample_vals = series.dropna().unique()[:5].tolist()
    # Dates display as plain YYYY-MM-DD; a midnight 00:00:00 timestamp on
    # every sample would be pure noise for a column that has no time
    # component (Timestamp.date() is a no-op on ones that do have one).
    if pd.api.types.is_datetime64_any_dtype(series):
        sample_strs = [str(v.date()) if hasattr(v, "date") else str(v) for v in sample_vals]
    else:
        sample_strs = [str(v) for v in sample_vals]
    return {
        "name": name,
        "dtype": str(series.dtype),
        "inferred_role": role,
        "null_count": int(series.isna().sum()),
        "null_pct": round(float(series.isna().mean()) * 100, 2),
        "distinct_count": int(series.nunique()),
        "sample_values": sample_strs,
    }


def override_column_role(dataset_id: str, table_name: str, column_name: str, new_role: str) -> dict:
    """Lets the person correct a detected column role.

    NOT a cosmetic relabel: a column forced to role="date" or "metric"
    is actually re-parsed with the same logic ingestion uses and the
    DuckDB table is rewritten with the converted dtype -- otherwise
    downstream date_trunc()/sum() would crash on a VARCHAR column.
    The conversion is committed only if it clears the same 80% success
    bar as ingestion; otherwise this raises ColumnOverrideError with the
    measured rate and changes nothing.
    """
    if new_role not in VALID_ROLES:
        raise ColumnOverrideError(
            f"Unknown role '{new_role}'. Choose one of: {', '.join(sorted(VALID_ROLES))}."
        )
    info = catalog.get_table_info(dataset_id, table_name)
    if not info:
        raise ColumnOverrideError(f"Table '{table_name}' not found.")
    col_meta = next((c for c in info["columns"] if c["name"] == column_name), None)
    if col_meta is None:
        raise ColumnOverrideError(f"Column '{column_name}' not found in '{table_name}'.")

    con = catalog.get_connection(dataset_id)
    try:
        df = con.execute(f'SELECT * FROM "{table_name}"').df()
    finally:
        con.close()

    series = df[column_name]
    is_dt = pd.api.types.is_datetime64_any_dtype(series)
    is_num = pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series)
    non_null = int(series.notna().sum())
    notes = []
    converted = None  # "date" | "metric" | "text" when storage type changed

    if new_role == "date":
        if not is_dt:
            if non_null == 0:
                raise ColumnOverrideError(f"Column '{column_name}' has no values to parse as dates.")
            src = series
            if is_num:
                # e.g. 20240115 stored as a float: parse as digits, not epoch ns
                if not (src.dropna() % 1 == 0).all():
                    raise ColumnOverrideError(
                        f"Column '{column_name}' holds non-integer numbers, which can't be read as dates."
                    )
                src = src.dropna().astype("int64").astype(str).reindex(series.index)
            parsed = pd.to_datetime(src, errors="coerce")
            rate = int(parsed.notna().sum()) / non_null
            if not rate > _MIN_PARSE_SUCCESS:
                raise ColumnOverrideError(
                    f"Can't treat '{column_name}' as a date: only {rate * 100:.0f}% of its values "
                    f"parse as dates (need more than {_MIN_PARSE_SUCCESS * 100:.0f}%). Nothing was changed."
                )
            lost = non_null - int(parsed.notna().sum())
            if lost:
                notes.append(f"{lost} value(s) couldn't be parsed and were set to empty.")
            df[column_name] = parsed
            converted = "date"

    elif new_role == "metric":
        if is_dt:
            raise ColumnOverrideError(
                f"'{column_name}' is a date column; it can't be treated as a numeric metric."
            )
        if not is_num:
            if non_null == 0:
                raise ColumnOverrideError(f"Column '{column_name}' has no values to read as numbers.")
            cleaned = series.apply(_clean_numeric_value)
            rate = int(cleaned.notna().sum()) / non_null
            if rate < _MIN_PARSE_SUCCESS:
                raise ColumnOverrideError(
                    f"Can't treat '{column_name}' as a metric: only {rate * 100:.0f}% of its values "
                    f"convert to numbers (need at least {_MIN_PARSE_SUCCESS * 100:.0f}%). Nothing was changed."
                )
            lost = non_null - int(cleaned.notna().sum())
            if lost:
                notes.append(f"{lost} value(s) weren't numeric and were set to empty.")
            df[column_name] = pd.to_numeric(cleaned, errors="coerce")
            converted = "metric"

    else:  # category / text / id
        if is_dt:
            # keep storage consistent with the label: a non-date role on a
            # TIMESTAMP column would break category filters downstream
            df[column_name] = series.dt.strftime("%Y-%m-%d %H:%M:%S").where(series.notna(), None)
            converted = "text"

    if converted:
        con = catalog.get_connection(dataset_id)
        try:
            con.register("df_temp", df)
            con.execute(f'CREATE OR REPLACE TABLE "{table_name}" AS SELECT * FROM df_temp')
        finally:
            con.close()

    # --- update the saved catalog record ---
    new_meta = _profile_column(column_name, df[column_name], new_role)
    info["columns"] = [new_meta if c["name"] == column_name else c for c in info["columns"]]

    parsed_dates = [c for c in info.get("date_columns_parsed", []) if c != column_name]
    if new_role == "date":
        parsed_dates.append(column_name)
    info["date_columns_parsed"] = parsed_dates

    numeric_cleaned = [c for c in info.get("numeric_columns_cleaned", []) if c != column_name]
    if new_role == "metric" and converted == "metric":
        numeric_cleaned.append(column_name)
    info["numeric_columns_cleaned"] = numeric_cleaned

    dq = info.get("data_quality")
    if dq:
        n_rows = len(df)
        missing = int(df.isna().sum().sum())
        cells = n_rows * len(df.columns)
        missing_pct = (missing / cells) if cells else 0.0
        dup_pct = (dq.get("duplicate_row_count", 0) / n_rows) if n_rows else 0.0
        if new_role == "date":
            dq["invalid_date_columns"] = [c for c in dq.get("invalid_date_columns", []) if c != column_name]
            dq["warnings"] = [
                w for w in dq.get("warnings", [])
                if not w.startswith(f"Column '{column_name}' looks like a date")
            ]
        dq["missing_value_count"] = missing
        dq["missing_cell_pct"] = round(missing_pct * 100, 2)
        dq["high_null_columns"] = [c for c in df.columns if df[c].isna().mean() > 0.5]
        dq["numeric_columns_cleaned"] = numeric_cleaned
        dq["quality_score"] = _compute_quality_score(
            missing_pct, dup_pct, len(dq.get("invalid_date_columns", []))
        )
        if notes:
            dq["warnings"] = dq.get("warnings", []) + [f"Override on '{column_name}': {n}" for n in notes]

    catalog.register_table(dataset_id, table_name, info)
    return {"table": info, "column": new_meta, "notes": notes}