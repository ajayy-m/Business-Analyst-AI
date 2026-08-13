# AI Business Analyst

Upload business data, ask questions in plain English, get grounded
answers with charts, statistical backing, and root-cause analysis —
not just a chatbot guessing at your numbers.

**Core principle:** the LLM plans and narrates, but never does
arithmetic on your data. Every number in every answer is computed by
SQL or Python — the LLM only writes the sentences around it.

## What it does right now

Ask something like *"Why did revenue decrease?"* and it will:

1. Classify the question (diagnostic investigation vs. simple lookup)
2. Run a deterministic root-cause drill-down: check every dimension in
   your schema, find which one explains the change, recurse one level
   deeper (e.g. "Product B" → "concentrated in the APAC region within
   Product B")
3. Auto-join across tables if the answer requires it — e.g. a decline
   concentrated in a customer *segment* that only exists in a separate
   customers table
4. Check whether the deviation is statistically real (z-score) or just
   noise
5. Generate chart specs (trend line + driver breakdown)
6. Have the LLM write up the findings in plain English

All of this — the SQL, the drill-down, the stats, the charts — is
computed by deterministic code. The LLM's job is narrow: turn
pre-computed findings into readable sentences.

## Setup

```bash
cd backend
pip install -r requirements.txt
```

Get a free Groq API key (no credit card) at
https://console.groq.com/keys, then copy `.env.example` to `.env` in
`backend/` and paste your key in:
```
GROQ_API_KEY=gsk_...
```

Run it:
```bash
uvicorn app.main:app --reload --port 8000
```

Interactive docs at http://localhost:8000/docs.

## Try it

1. Upload the sample data (two related tables under one dataset):
```bash
curl -X POST "http://localhost:8000/datasets/demo/upload" \
  -F "table_name=sales" -F "file=@sample_sales.csv"

curl -X POST "http://localhost:8000/datasets/demo/upload" \
  -F "table_name=customers" -F "file=@sample_customers.csv"
```

2. Ask a diagnostic question:
```bash
curl -X POST "http://localhost:8000/datasets/demo/ask" \
  --data-urlencode "question=Why did revenue decrease?"
```

3. Or use `/docs` for all of this through a browser instead of curl.

`sample_sales.csv` has a deliberate Q3 decline concentrated in
APAC/Product B. `sample_customers.csv` adds a `segment` column
(Enterprise/SMB) correlated with that decline, so you can see the
diagnostic engine discover a cross-table driver on its own.

## Project structure

```
backend/
  app/
    main.py                      API routes
    agent.py                     LLM calls: classify, generate_sql, synthesize
    visualization.py             Chart spec generation (Vega-Lite JSON)
    data/
      ingestion.py                CSV/Excel parsing, validation, schema inference
      catalog.py                  DuckDB connections + metadata store
      relationships.py            Auto-detects joinable tables (shared ID columns)
      models.py                   Pydantic schemas
    analytics/
      sql_safety.py                Safe read-only SQL execution
      multi_table.py               Resolves + auto-joins tables a question needs
      diagnostics.py               Root-cause drill-down (the core "why" engine)
      forecasting.py               Linear trend + confidence interval
      anomaly_dashboard.py         Proactive scan across all metrics/dimensions
  requirements.txt
  .env.example
sample_sales.csv
sample_customers.csv
```

## API reference

| Endpoint | Purpose |
|---|---|
| `POST /datasets/{id}/upload` | Upload a CSV/Excel file as a named table |
| `GET /datasets/{id}/catalog` | Full schema metadata (JSON) |
| `GET /datasets/{id}/catalog/text` | Schema as LLM-ready text |
| `POST /datasets/{id}/query` | Raw read-only SQL (manual testing) |
| `POST /datasets/{id}/ask` | **Main endpoint.** Question in, classified + answered |
| `POST /datasets/{id}/forecast` | Trend projection with confidence band |
| `GET /datasets/{id}/anomalies` | Proactive scan for statistically unusual deviations |

## How the pieces fit together

**Ingestion** (`data/ingestion.py`) infers column types and semantic
roles (date/id/category/metric) on upload, and stores schema + stats
in a catalog (`data/catalog.py`) — this catalog is what the LLM reads
for grounding, not raw data, so prompts stay small regardless of
dataset size.

**Multi-table** (`data/relationships.py` + `analytics/multi_table.py`)
detects joinable tables by shared ID-role columns and silently builds
a joined view whenever a metric or dimension the question needs lives
in a different table than the one being queried. The LLM never writes
or knows about a JOIN — it only ever names columns.

**The agent** (`agent.py`) makes three kinds of LLM calls, each narrow
and structured (tool-calling, not free-text parsing):
- `classify_and_extract` — diagnostic vs. lookup, plus which
  metric/date/filters are relevant
- `generate_sql` — for simple lookups, one SQL SELECT
- `synthesize_answer` / `synthesize_diagnostic_answer` — turns
  pre-computed results into prose, never doing math itself

**Diagnostics** (`analytics/diagnostics.py`) is deliberately *not* an
LLM call. It systematically checks every categorical dimension
available (across joined tables), finds which one explains the
largest share of a change via contribution math, recurses one level
deeper, and checks statistical significance with a z-score. This is
what turns "revenue dropped 4.9%" into "driven by Product B,
concentrated in the SMB segment, and it's a real deviation not noise."

**Forecasting** (`analytics/forecasting.py`) fits a linear trend with
a 95% confidence band from residual spread, and reports R² honestly —
low R² means the trend explains little of the variance, and the
system doesn't hide that.

## What's implemented

- ✅ Multi-file/multi-table ingestion with schema + role inference
- ✅ Text-to-SQL for simple lookups
- ✅ Deterministic root-cause drill-down (2 levels deep + anomaly check)
- ✅ Auto-join across tables, driver discovery works across the join
- ✅ Chart spec generation (trend, driver breakdown, forecast band)
- ✅ Forecasting (linear trend + confidence interval)
- ✅ Proactive anomaly dashboard scan
- ✅ Runs entirely on Groq's free tier — no billing required

## What's next

- **Frontend** — currently API-only, testable via `/docs`. A real UI
  is the next milestone.
- **Anomaly dashboard across joins** — `/anomalies` currently only
  scans single tables; extending it to scan joined dimensions too
  (like the diagnostic engine already does) is a natural next step.
- **Customer segmentation (RFM/clustering)** — not yet built; was in
  the original ML scope alongside forecasting/anomaly detection.
- **Edge-case testing** — planned after the frontend exists, so
  testing and demo-polish happen together.

## Known limitations (worth knowing, not hiding)

- Relationship detection requires an exact shared column name between
  tables (e.g. `customer_id` in both) — it won't infer a join if the
  key is named differently in each table.
- The diagnostic drill-down goes 2 levels deep by design (dimension →
  sub-dimension); it won't chase a 3rd level automatically.
- Forecasting is a simple linear trend, not ARIMA/Prophet — appropriate
  for the small datasets this is built for, and every number is
  traceable to a formula rather than a black-box call, but it won't
  capture seasonality.
- Running on Groq's free-tier open model (not Claude/GPT-4) means
  occasional SQL generation mistakes; the one-shot self-correction
  retry catches most of them, but not all.
