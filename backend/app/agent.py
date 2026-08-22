"""
Phase 2 agent -- now running on Groq's free tier instead of the Anthropic
API, so this works without any billing setup.

Same two-call design as before:
1. generate_sql   -- question + schema -> one SQL SELECT, via OpenAI-style
                      function calling (Groq's API is OpenAI-compatible).
2. synthesize_answer -- question + SQL + computed RESULT -> plain-English
                      answer. The LLM only ever sees aggregated numbers,
                      never raw rows, and never does arithmetic itself.

Swapping providers again later (e.g. to Anthropic once you have credits,
or to a local Ollama model) only requires editing this file -- main.py
doesn't need to change, since it just calls generate_sql/synthesize_answer.
"""
import json
from groq import Groq

client = Groq()  # reads GROQ_API_KEY from the environment
MODEL = "openai/gpt-oss-120b"  # Groq deprecated the llama-3.3-70b-versatile line; this is their current flagship

SQL_SYSTEM_PROMPT = """You are a SQL analyst working with a DuckDB database.
You are given a schema (tables, columns, types, sample values) and a
business question in plain English.

Write exactly ONE read-only SQL SELECT query that answers the question.

Rules:
- Only reference tables and columns that appear in the schema.
- Never write INSERT/UPDATE/DELETE/DROP/ALTER/CREATE -- read-only only.
- Use DuckDB SQL syntax, e.g. date_trunc('quarter', some_date_col).
- If the question implies a comparison over time (e.g. "why did X change",
  "how did X grow/decline"), write a query that returns the relevant
  breakdown (e.g. by quarter, by category) AND compute a percent-change
  column using a window function, so the magnitude of change is already
  calculated -- never leave percent-change math to be estimated later.
  Example pattern:
    WITH base AS (
      SELECT date_trunc('quarter', order_date) AS period, sum(revenue) AS value
      FROM sales WHERE region = 'APAC' GROUP BY 1
    )
    SELECT period, value,
           round(100.0 * (value - lag(value) OVER (ORDER BY period))
                 / lag(value) OVER (ORDER BY period), 1) AS pct_change
    FROM base ORDER BY period
- Submit your query via the generate_sql tool. Do not include commentary."""

SQL_TOOL = {
    "type": "function",
    "function": {
        "name": "generate_sql",
        "description": "Submit the SQL SELECT query that answers the business question.",
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "A single read-only SQL SELECT statement.",
                }
            },
            "required": ["sql"],
        },
    },
}


def generate_sql(question: str, schema_context: str, error_context: str | None = None) -> str:
    user_msg = f"SCHEMA:\n{schema_context}\n\nQUESTION: {question}"
    if error_context:
        user_msg += (
            f"\n\nYour previous query failed with this error. "
            f"Fix it and submit a corrected query:\n{error_context}"
        )

    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=1000,
        messages=[
            {"role": "system", "content": SQL_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        tools=[SQL_TOOL],
        tool_choice={"type": "function", "function": {"name": "generate_sql"}},
    )

    message = response.choices[0].message
    if not message.tool_calls:
        raise ValueError("Model did not return a SQL query.")

    args = json.loads(message.tool_calls[0].function.arguments)
    return args["sql"]


SYNTHESIS_SYSTEM_PROMPT = """You are a business analyst explaining a query
result to a stakeholder.

You will be given a question, the SQL query that was run, and its result.

Write a concise answer (2-4 sentences) using ONLY the numbers present in
the result -- never invent, estimate, or recalculate a number that isn't
there. If a pct_change column is present, quote it directly rather than
computing your own percentage.

Formatting:
- Format currency with a dollar sign and thousands separators, e.g.
  $609,853 -- never raw floats like 609852.98.
- Round percentages to one decimal place, e.g. 12.4%.
- Plain prose only -- no markdown (no **bold**, no bullet points, no
  headers). The UI already highlights key figures with its own evidence
  chips, so markdown emphasis in the text is redundant and renders as
  literal asterisks, not bold.

Focus your explanation on the period or category the question is actually
about -- typically the most recent period, or wherever the change is
concentrated -- not on whichever number happens to be largest. If the
result shows a clear driver (a category/region that deviates most), name
it specifically. End with one short, concrete recommendation only if the
data genuinely supports one, and make sure it's about addressing the
decline/change in question -- not about investigating an unrelated good
period."""


def synthesize_answer(question: str, sql: str, columns: list, rows: list) -> str:
    # cap rows sent to the LLM -- the query itself should already have
    # aggregated to a small result set; this is a safety limit, not the
    # normal path
    result_preview = {"columns": columns, "rows": rows[:50]}

    user_msg = (
        f"QUESTION: {question}\n\n"
        f"SQL USED:\n{sql}\n\n"
        f"RESULT:\n{result_preview}"
    )

    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=500,
        messages=[
            {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
    )

    return response.choices[0].message.content


# ---------------------------------------------------------------------
# Phase 3: diagnostic classification + root-cause synthesis
# ---------------------------------------------------------------------

DIAGNOSTIC_EXTRACT_TOOL = {
    "type": "function",
    "function": {
        "name": "extract_diagnostic_params",
        "description": (
            "Decide how to answer this question -- as a root-cause "
            "investigation, a simple data lookup, or a question about "
            "the dataset's structure -- and extract whatever parameters "
            "that path needs."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "intent": {
                    "type": "string",
                    "enum": ["diagnostic", "lookup", "meta"],
                    "description": (
                        "'diagnostic' for why/what-caused/what-drove/how-did-X-change "
                        "questions about the DATA. 'lookup' for direct factual "
                        "questions about the data, e.g. 'what was revenue in Q3'. "
                        "'meta' for questions about the DATASET ITSELF rather than "
                        "its values -- e.g. 'what columns/metrics does this dataset "
                        "have', 'what does column X represent', 'how many rows are "
                        "there', 'what tables exist'. Use 'meta' whenever the "
                        "question is about structure/schema, not a computed number."
                    ),
                },
                "metric_column": {
                    "type": "string",
                    "description": (
                        "The numeric column the question is about, e.g. 'revenue'. "
                        "Must exist in the schema. Only needed for 'diagnostic' "
                        "intent -- omit for 'lookup' and 'meta'."
                    ),
                },
                "date_column": {
                    "type": "string",
                    "description": (
                        "The date column to use for time comparisons. Must exist "
                        "in the schema. Only needed for 'diagnostic' intent -- "
                        "omit for 'lookup' and 'meta'."
                    ),
                },
                "filters": {
                    "type": "object",
                    "description": (
                        "Dimension filters explicitly mentioned in the question, "
                        "e.g. {\"region\": \"APAC\"}. Empty object if none mentioned -- "
                        "do not guess filters that weren't stated."
                    ),
                    "additionalProperties": {"type": "string"},
                },
            },
            "required": ["intent"],
        },
    },
}

CLASSIFY_SYSTEM_PROMPT = """You analyze a business question against a
database schema to decide how to answer it.

Classify as 'diagnostic' if the question asks why something happened, what
caused/drove a change, or how something changed over time in a way that
implies investigation. Classify as 'lookup' for direct factual questions
that just want a computed number or list from the DATA. Classify as 'meta'
for questions about the dataset's STRUCTURE rather than its values -- what
columns/metrics/tables exist, what a column represents, how many rows
there are, what kind of data this is. A question with no clear metric or
time period in it, asking about the dataset in general, is almost always
'meta'.

For 'diagnostic' questions, also extract which metric column and date
column from the schema are relevant, and any dimension filters explicitly
stated in the question. Only include filters the question actually
mentions -- never guess. For 'lookup' and 'meta' questions, you do not
need to extract metric_column or date_column."""


def classify_and_extract(question: str, schema_context: str) -> dict:
    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=500,
        messages=[
            {"role": "system", "content": CLASSIFY_SYSTEM_PROMPT},
            {"role": "user", "content": f"SCHEMA:\n{schema_context}\n\nQUESTION: {question}"},
        ],
        tools=[DIAGNOSTIC_EXTRACT_TOOL],
        tool_choice={"type": "function", "function": {"name": "extract_diagnostic_params"}},
    )

    message = response.choices[0].message
    if not message.tool_calls:
        raise ValueError("Model did not return classification.")

    return json.loads(message.tool_calls[0].function.arguments)


DIAGNOSTIC_SYNTHESIS_SYSTEM_PROMPT = """You are a business analyst writing
up the result of a root-cause investigation for a stakeholder.

You will be given a JSON object with:
- overall: the metric's value in the latest vs previous period, and pct_change
- level1_driver: the single category (e.g. a product or region) that
  explains the largest share of that change, with its own contribution_pct
- level2_driver: optionally, a further breakdown within level1_driver
  (e.g. a specific region within the product that drove the change)
- anomaly: a z_score and is_notable flag indicating whether this deviation
  is statistically unusual or within normal noise

Write a concise summary (3-5 sentences) in this shape, using ONLY the
numbers provided -- never invent or recompute a number:
1. State the overall change with its pct_change, formatted as a percentage.
2. Name the level1_driver and its contribution_pct as the primary cause.
3. If level2_driver is present, name it as a further concentration within
   the level1 finding.
4. If anomaly.is_notable is true, note that this is a statistically
   significant deviation, not normal variation. If is_notable is false or
   null, don't claim significance.
5. End with one specific, concrete recommendation tied to the exact driver
   found (name the actual category/product/region) -- not generic advice.

Format currency with $ and thousands separators. Format percentages to one
decimal place. Plain prose only -- no markdown (no **bold**, no bullet
points, no headers); the UI's evidence chips already highlight key
figures, so markdown emphasis would be redundant and renders as literal
asterisks, not bold."""


META_SYSTEM_PROMPT = """You are describing a dataset's structure to a
business user who understands analytics but has no data-engineering
background. You will be given the dataset's schema -- table names,
column names, each column's inferred role (date/id/category/metric/text),
data type, row counts, distinct-value counts, and a few sample values.

Answer the question using ONLY what's in the schema below. You may
reasonably describe what a column likely represents based on its name
and role (e.g. a 'metric' column named 'revenue' represents sales
revenue) -- but never invent statistics, business context, or specifics
that aren't present in the schema. If something genuinely can't be
determined from the schema, say so plainly rather than guessing
confidently.

Keep it complete within the space you have: if several columns share an
obvious naming pattern (e.g. q_p1, q_p2, q_p3, q_p4), describe the
pattern ONCE ("q_p1 through q_p4 are numeric values for four periods or
categories, exact meaning unclear from the name alone") rather than a
full repeated sentence per column -- a full answer that covers every
table concisely is more useful than an exhaustive one that gets cut off
partway through.

Formatting: plain prose only, no markdown (no **bold**, no bullet
points, no headers) -- the UI renders this as plain text."""


def synthesize_meta_answer(question: str, schema_context: str) -> str:
    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=800,
        messages=[
            {"role": "system", "content": META_SYSTEM_PROMPT},
            {"role": "user", "content": f"SCHEMA:\n{schema_context}\n\nQUESTION: {question}"},
        ],
    )
    return response.choices[0].message.content


def synthesize_diagnostic_answer(question: str, findings: dict) -> str:
    user_msg = f"QUESTION: {question}\n\nFINDINGS:\n{json.dumps(findings, default=str)}"

    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=500,
        messages=[
            {"role": "system", "content": DIAGNOSTIC_SYNTHESIS_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
    )

    return response.choices[0].message.content