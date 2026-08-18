"""
Chart generation -- produces Vega-Lite JSON specs from already-computed
data (diagnostic findings or query results). No LLM involved: this is
pure data shaping, same "don't let the model touch the numbers"
principle as everywhere else in this app.

Vega-Lite specs are a portable, declarative chart format -- the frontend
can render them directly with vega-embed/react-vega without the backend
needing to draw pixels.
"""

VEGA_SCHEMA = "https://vega.github.io/schema/vega-lite/v5.json"


def build_trend_chart(period_series: list, metric_label: str) -> dict:
    """Line chart of a metric over time -- the 'overall' picture."""
    period_values = [p["period"] for p in period_series]
    return {
        "$schema": VEGA_SCHEMA,
        "title": f"{metric_label} by quarter",
        "data": {"values": period_series},
        "mark": {"type": "line", "point": True},
        "encoding": {
            "x": {
                "field": "period", "type": "temporal", "title": "Quarter",
                # constrain ticks to only the actual data points -- without
                # this Vega-Lite defaults to a continuous daily scale and
                # renders dozens of unwanted intermediate tick marks
                "axis": {"format": "%b %Y", "values": period_values},
            },
            "y": {"field": "value", "type": "quantitative", "title": metric_label},
            "tooltip": [
                {"field": "period", "type": "temporal", "title": "Quarter"},
                {"field": "value", "type": "quantitative", "title": metric_label, "format": ",.0f"},
            ],
        },
        "width": 500,
        "height": 250,
    }


def build_driver_bar_chart(level1_driver: dict | None, level2_driver: dict | None, metric_label: str) -> dict | None:
    """
    Grouped bar chart: previous vs latest value for the top driver(s)
    found by the diagnostic drill-down -- makes the "here's what changed"
    finding visually obvious at a glance.
    """
    if not level1_driver:
        return None

    rows = []
    label1 = f"{level1_driver['dimension']}: {level1_driver['value']}"
    rows.append({"category": label1, "period": "Previous", "value": level1_driver["value_prev"]})
    rows.append({"category": label1, "period": "Latest", "value": level1_driver["value_latest"]})

    if level2_driver:
        # deliberately short -- "(within X)" was getting clipped by the
        # chart's bottom margin at a rotated angle; the grouping next to
        # label1 already makes the relationship clear without it
        label2 = f"{level2_driver['dimension']}: {level2_driver['value']}"
        rows.append({"category": label2, "period": "Previous", "value": level2_driver["value_prev"]})
        rows.append({"category": label2, "period": "Latest", "value": level2_driver["value_latest"]})

    return {
        "$schema": VEGA_SCHEMA,
        "title": "Driver breakdown: previous vs. latest period",
        "data": {"values": rows},
        "mark": "bar",
        "encoding": {
            "x": {
                "field": "category", "type": "nominal", "title": None,
                "axis": {"labelAngle": -15, "labelLimit": 240, "labelPadding": 4},
            },
            "y": {"field": "value", "type": "quantitative", "title": metric_label},
            "color": {
                "field": "period", "type": "nominal", "title": "Period",
                "scale": {"domain": ["Previous", "Latest"], "range": ["#94a3b8", "#ef4444"]},
            },
            "xOffset": {"field": "period"},
            "tooltip": [
                {"field": "category", "type": "nominal"},
                {"field": "period", "type": "nominal"},
                {"field": "value", "type": "quantitative", "format": ",.0f"},
            ],
        },
        "width": 480,
        "height": 300,
        "padding": {"bottom": 20, "left": 20, "top": 5, "right": 5},
    }


def build_forecast_chart(history: list, forecast: list, metric_label: str) -> dict:
    """
    Historical values (solid line) + forecasted values (dashed, with a
    shaded confidence band) on one chart -- makes the projection's
    uncertainty visible rather than presenting a single confident line.
    """
    hist_points = [{"period": h["period"], "value": h["value"], "series": "Historical"} for h in history]
    forecast_points = [{"period": f["period"], "value": f["value"], "series": "Forecast"} for f in forecast]
    all_periods = [p["period"] for p in hist_points + forecast_points]

    band_layer = {
        "data": {"values": forecast},
        "mark": {"type": "area", "opacity": 0.15, "color": "#2a78d6"},
        "encoding": {
            "x": {"field": "period", "type": "temporal", "axis": {"format": "%b %Y", "values": all_periods}},
            "y": {"field": "lower", "type": "quantitative"},
            "y2": {"field": "upper"},
        },
    }
    line_layer = {
        "data": {"values": hist_points + forecast_points},
        "mark": {"type": "line", "point": True},
        "encoding": {
            "x": {"field": "period", "type": "temporal", "title": "Period", "axis": {"format": "%b %Y", "values": all_periods}},
            "y": {"field": "value", "type": "quantitative", "title": metric_label},
            "strokeDash": {
                "field": "series", "type": "nominal",
                "scale": {"domain": ["Historical", "Forecast"], "range": [[0, 0], [4, 4]]},
            },
            "color": {
                "field": "series", "type": "nominal",
                "scale": {"domain": ["Historical", "Forecast"], "range": ["#2a78d6", "#94a3b8"]},
            },
            "tooltip": [
                {"field": "period", "type": "temporal"},
                {"field": "value", "type": "quantitative", "format": ",.0f"},
                {"field": "series", "type": "nominal"},
            ],
        },
    }

    return {
        "$schema": VEGA_SCHEMA,
        "title": f"{metric_label} forecast (shaded band = 95% confidence)",
        "layer": [band_layer, line_layer],
        "width": 550,
        "height": 280,
    }


def build_chart_from_query_result(columns: list, rows: list) -> dict | None:
    """
    For the simple lookup path: auto-pick a reasonable chart from a raw
    SQL result, based on column count/types. Returns None if the result
    doesn't look chart-worthy (e.g. a single scalar value).
    """
    if not rows or len(columns) < 2:
        return None

    sample = rows[0]
    numeric_cols = [c for c in columns if isinstance(sample.get(c), (int, float))]
    non_numeric_cols = [c for c in columns if c not in numeric_cols]

    if not numeric_cols or not non_numeric_cols:
        return None

    x_field = non_numeric_cols[0]
    y_field = numeric_cols[0]

    # crude date detection by field name, good enough for a default chart
    is_temporal = any(k in x_field.lower() for k in ["date", "period", "quarter", "month", "year"])
    x_encoding = {"field": x_field, "type": "temporal" if is_temporal else "nominal"}
    if is_temporal:
        # same fix as build_trend_chart -- constrain ticks to actual data
        # points instead of a default continuous daily scale
        x_encoding["axis"] = {"format": "%b %Y", "values": [r[x_field] for r in rows]}

    return {
        "$schema": VEGA_SCHEMA,
        "title": f"{y_field} by {x_field}",
        "data": {"values": rows},
        "mark": {"type": "line", "point": True} if is_temporal else "bar",
        "encoding": {
            "x": x_encoding,
            "y": {"field": y_field, "type": "quantitative"},
            "tooltip": [
                {"field": x_field},
                {"field": y_field, "type": "quantitative", "format": ",.0f"},
            ],
        },
        "width": 500,
        "height": 280,
    }