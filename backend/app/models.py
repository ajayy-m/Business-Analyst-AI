from pydantic import BaseModel
from typing import Optional


class ColumnInfo(BaseModel):
    name: str
    dtype: str
    inferred_role: Optional[str] = None  # e.g. "date", "id", "metric", "category"
    null_count: int
    null_pct: float
    distinct_count: int
    sample_values: list


class TableInfo(BaseModel):
    dataset_id: str
    table_name: str
    row_count: int
    columns: list[ColumnInfo]
    source_filename: str


class DatasetSummary(BaseModel):
    dataset_id: str
    tables: list[str]


class UploadResponse(BaseModel):
    dataset_id: str
    table_name: str
    row_count: int
    column_count: int
    columns: list[ColumnInfo]
    warnings: list[str]
