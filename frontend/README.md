# AI Business Analyst — Frontend

React + Vite frontend for the backend built in `../backend`.

## Setup

```bash
npm install
```

## Run

The backend must be running first (`uvicorn app.main:app --reload --port 8000` from `../backend`). Then:

```bash
npm run dev
```

Opens at http://localhost:5173. The dev server proxies `/api/*` to
`http://127.0.0.1:8000` (configured in `vite.config.js`), so the
frontend never needs the backend's port hardcoded anywhere.

## Structure

```
src/
  App.jsx                  Tab layout: Dashboard / Ask / Forecast / At-risk
  api.js                   All backend calls in one place
  components/
    Sidebar.jsx              Dataset selection + file upload
    Dashboard.jsx            Proactive anomaly flags (GET /anomalies)
    AskPanel.jsx             Question box, answer + charts, click-to-drill
    ForecastPanel.jsx        Trend projection with confidence band
    ChurnPanel.jsx           Churn model results + at-risk customer table
    VegaChart.jsx            Renders backend Vega-Lite specs, handles clicks
    EvidenceChip.jsx         The clickable "here's the computation" tags
```

## Design notes

Colors, fonts, and the "evidence chip" signature element are defined in
`src/index.css` via Tailwind v4's `@theme` directive — see that file's
comments for the reasoning (a ledger-inspired palette, monospace for
every number, grounded in the product's actual "LLM narrates, code
computes" principle rather than decorative choices).

## Click-to-drill

Clicking a bar in the driver-breakdown chart (in the Ask tab) calls
`POST /datasets/{id}/diagnose` directly with a filter derived from the
clicked bar — this is a separate, LLM-free backend endpoint built
specifically so drilling feels instant and doesn't spend Groq
rate-limit budget on every click.
