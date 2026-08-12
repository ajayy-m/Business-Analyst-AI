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
MODEL = "llama-3.3-70b-versatile"

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