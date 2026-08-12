# AI Business Analyst — Phase 1: Data Foundation

Ingestion → DuckDB → Catalog → Query API. No LLM yet — this proves the
data pipeline produces correct, queryable results before any agent
reasoning is layered on top.

## Run it

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Server runs at http://localhost:8000. Interactive API docs at
http://localhost:8000/docs (FastAPI auto-generates this).

## Try it

1. Upload a CSV to create a table in a dataset:
```bash
curl -X POST "http://localhost:8000/datasets/demo/upload" \
  -F "table_name=sales" \
  -F "file=@sample_sales.csv"
```

2. Inspect the inferred schema (this is the "catalog" the LLM agent will
   read in Phase 2/3 instead of raw data):
```bash
curl http://localhost:8000/datasets/demo/catalog/text
```

3. Run a read-only SQL query directly:
```bash
curl -X POST "http://localhost:8000/datasets/demo/query" \
  --data-urlencode "sql=SELECT region, sum(revenue) FROM sales GROUP BY 1"
```

`sample_sales.csv` is included — synthetic data with a deliberate Q3
APAC/Product B revenue decline baked in, so you have a known anomaly to
test diagnostic questions against once the agent exists.

## What's implemented

- CSV/Excel upload with automatic column name cleaning
- Type + semantic role inference per column (date / id / category / metric / text)
- Automatic date-column parsing
- Basic data quality validation (duplicates, high-null columns)
- One DuckDB file per dataset (isolated, portable, zero server infra)
- Persistent JSON catalog of every table's schema and stats
- `catalog_as_llm_context()` — renders the schema as compact text, ready
  to drop into an LLM prompt in Phase 2
- Read-only SQL query endpoint with a write-query safety block

## What's next (Phase 2)

Wire up the LLM: a `text_to_sql` tool that takes a natural-language
question + the catalog context and produces SQL against these tables,
then a synthesis call that turns the query result into a written answer.

## Project structure

```
backend/
  app/
    main.py       - FastAPI routes
    ingestion.py  - parsing, validation, schema inference
    catalog.py    - DuckDB connections + metadata store
    models.py     - Pydantic schemas
  requirements.txt
sample_sales.csv   - synthetic test data
```
