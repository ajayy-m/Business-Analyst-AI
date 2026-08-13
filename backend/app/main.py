import shutil
import uuid
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()  # must run before `app.agent` is imported so GROQ_API_KEY is set

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import groq

from app.data import ingestion, catalog
from app.analytics import sql_safety, diagnostics, forecasting, anomaly_dashboard
from app import agent, visualization

app = FastAPI(title="AI Business Analyst API", version="0.1.0-phase1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten before real deployment
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = Path(__file__).parent.parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/datasets/{dataset_id}/upload")
async def upload_file(
    dataset_id: str,
    table_name: str = Form(...),
    file: UploadFile = File(...),
):
    """
    Upload a CSV/Excel file into a named table within a dataset.
    A 'dataset' groups related tables (e.g. sales, customers, products
    for one company) so questions can join across them.
    """
    if not file.filename.lower().endswith((".csv", ".xlsx", ".xls")):
        raise HTTPException(400, "Only .csv, .xlsx, .xls files are supported.")

    dest_path = UPLOAD_DIR / f"{dataset_id}_{table_name}_{file.filename}"
    with open(dest_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        result = ingestion.ingest_file(dataset_id, table_name, str(dest_path), file.filename)
    except Exception as e:
        raise HTTPException(400, f"Failed to ingest file: {e}")

    return result


@app.get("/datasets")
def list_datasets():
    return {"datasets": catalog.list_datasets()}


@app.get("/datasets/{dataset_id}/catalog")
def get_catalog(dataset_id: str):
    ds = catalog.get_dataset_catalog(dataset_id)
    if not ds:
        raise HTTPException(404, "Dataset not found.")
    return ds


@app.get("/datasets/{dataset_id}/catalog/text")
def get_catalog_text(dataset_id: str):
    """Returns the LLM-ready schema summary -- useful to sanity check what
    context the agent will see before we wire up the LLM in Phase 2."""
    return {"context": catalog.catalog_as_llm_context(dataset_id)}


@app.post("/datasets/{dataset_id}/query")
def run_query(dataset_id: str, sql: str = Form(...)):
    """Direct SQL execution endpoint -- read-only, for manual testing."""
    ds = catalog.get_dataset_catalog(dataset_id)
    if not ds:
        raise HTTPException(404, "Dataset not found.")

    try:
        return sql_safety.run_safe_query(dataset_id, sql)
    except sql_safety.UnsafeQueryError as e:
        raise HTTPException(400, str(e))
    except sql_safety.QueryExecutionError as e:
        raise HTTPException(400, f"Query failed: {e}")


@app.post("/datasets/{dataset_id}/ask/simple")
def ask_question_simple(dataset_id: str, question: str = Form(...)):
    """
    Phase 2's single-query version -- kept as a fast/cheap path (one SQL
    query, no multi-step investigation) and as a baseline to compare
    against the Phase 3 agent below.
    """
    ds = catalog.get_dataset_catalog(dataset_id)
    if not ds:
        raise HTTPException(404, "Dataset not found.")

    schema_context = catalog.catalog_as_llm_context(dataset_id)

    try:
        sql = agent.generate_sql(question, schema_context)
        try:
            result = sql_safety.run_safe_query(dataset_id, sql)
        except sql_safety.UnsafeQueryError as e:
            raise HTTPException(400, str(e))
        except sql_safety.QueryExecutionError as e:
            sql = agent.generate_sql(question, schema_context, error_context=str(e))
            try:
                result = sql_safety.run_safe_query(dataset_id, sql)
            except sql_safety.QueryExecutionError as e2:
                raise HTTPException(
                    400, f"Could not answer this question. Last error: {e2}"
                )

        answer = agent.synthesize_answer(question, sql, result["columns"], result["rows"])

    except groq.AuthenticationError:
        raise HTTPException(
            500,
            "Groq API key is missing or invalid. Check GROQ_API_KEY in your .env file.",
        )
    except groq.RateLimitError:
        raise HTTPException(
            429,
            "Groq's free-tier rate limit was hit (30 requests/min). Wait a "
            "moment and try again.",
        )
    except groq.BadRequestError as e:
        raise HTTPException(500, f"Groq API request error: {e}")
    except groq.APIConnectionError:
        raise HTTPException(
            503, "Couldn't reach the Groq API -- check your internet connection."
        )

    return {
        "question": question,
        "sql": sql,
        "columns": result["columns"],
        "rows": result["rows"][:50],
        "answer": answer,
    }


@app.post("/datasets/{dataset_id}/ask")
def ask_question(dataset_id: str, question: str = Form(...)):
    """
    Phase 3: classifies the question, then routes to one of two paths:

    - 'diagnostic' (why/what-caused/what-drove questions): runs the
      deterministic root-cause drill-down (app/diagnostics.py) -- checks
      every dimension in the schema to find what explains the change,
      recurses one level deeper, and checks whether the deviation is
      statistically real. The LLM only narrates these pre-computed
      findings; it never does the arithmetic.
    - 'lookup' (direct factual questions): falls back to the single-query
      path from Phase 2.
    """
    ds = catalog.get_dataset_catalog(dataset_id)
    if not ds:
        raise HTTPException(404, "Dataset not found.")

    schema_context = catalog.catalog_as_llm_context(dataset_id)

    try:
        params = agent.classify_and_extract(question, schema_context)

        if params["intent"] == "diagnostic":
            try:
                findings = diagnostics.run_diagnostic(
                    dataset_id=dataset_id,
                    metric_column=params["metric_column"],
                    date_column=params["date_column"],
                    filters=params.get("filters") or {},
                )
            except diagnostics.DiagnosticError as e:
                raise HTTPException(400, f"Could not run diagnostic: {e}")

            answer = agent.synthesize_diagnostic_answer(question, findings)

            charts = {
                "trend": visualization.build_trend_chart(
                    findings["overall"]["period_series"], params["metric_column"]
                ),
                "driver_breakdown": visualization.build_driver_bar_chart(
                    findings["level1_driver"], findings["level2_driver"], params["metric_column"]
                ),
            }

            return {
                "question": question,
                "intent": "diagnostic",
                "findings": findings,
                "answer": answer,
                "charts": charts,
            }

        # lookup path -- same as /ask/simple
        sql = agent.generate_sql(question, schema_context)
        try:
            result = sql_safety.run_safe_query(dataset_id, sql)
        except sql_safety.UnsafeQueryError as e:
            raise HTTPException(400, str(e))
        except sql_safety.QueryExecutionError as e:
            sql = agent.generate_sql(question, schema_context, error_context=str(e))
            try:
                result = sql_safety.run_safe_query(dataset_id, sql)
            except sql_safety.QueryExecutionError as e2:
                raise HTTPException(
                    400, f"Could not answer this question. Last error: {e2}"
                )

        answer = agent.synthesize_answer(question, sql, result["columns"], result["rows"])

        chart = visualization.build_chart_from_query_result(result["columns"], result["rows"])

        return {
            "question": question,
            "intent": "lookup",
            "sql": sql,
            "columns": result["columns"],
            "rows": result["rows"][:50],
            "answer": answer,
            "chart": chart,
        }

    except groq.AuthenticationError:
        raise HTTPException(
            500,
            "Groq API key is missing or invalid. Check GROQ_API_KEY in your .env file.",
        )
    except groq.RateLimitError:
        raise HTTPException(
            429,
            "Groq's free-tier rate limit was hit (30 requests/min). Wait a "
            "moment and try again.",
        )
    except groq.BadRequestError as e:
        raise HTTPException(500, f"Groq API request error: {e}")
    except groq.APIConnectionError:
        raise HTTPException(
            503, "Couldn't reach the Groq API -- check your internet connection."
        )


@app.post("/datasets/{dataset_id}/forecast")
def forecast(
    dataset_id: str,
    metric_column: str = Form(...),
    date_column: str = Form(...),
    periods_ahead: int = Form(3),
    granularity: str = Form("month"),
):
    """
    Projects a metric forward using a linear trend fit to historical
    periods, with a 95% confidence band from the residual spread.
    Purely statistical -- no LLM involved. Low r_squared in the response
    means the trend explains little of the variance; treat the forecast
    with proportional skepticism in that case.
    """
    ds = catalog.get_dataset_catalog(dataset_id)
    if not ds:
        raise HTTPException(404, "Dataset not found.")

    try:
        result = forecasting.forecast_metric(
            dataset_id=dataset_id,
            metric_column=metric_column,
            date_column=date_column,
            periods_ahead=periods_ahead,
            granularity=granularity,
        )
    except forecasting.ForecastError as e:
        raise HTTPException(400, str(e))

    result["chart"] = visualization.build_forecast_chart(
        result["history"], result["forecast"], metric_column
    )
    return result


@app.get("/datasets/{dataset_id}/anomalies")
def get_anomalies(dataset_id: str, z_threshold: float = 1.5):
    """
    Proactive dashboard scan: checks every metric x category combination
    for a statistically unusual latest-period deviation, without the user
    asking a specific question. Complements (doesn't replace) the deeper
    2-level drill-down in /ask -- this is breadth-first across the whole
    schema, the diagnostic path is depth-first on one question.
    """
    ds = catalog.get_dataset_catalog(dataset_id)
    if not ds:
        raise HTTPException(404, "Dataset not found.")

    flags = anomaly_dashboard.scan_for_anomalies(dataset_id, z_threshold=z_threshold)
    return {"flags": flags, "count": len(flags)}