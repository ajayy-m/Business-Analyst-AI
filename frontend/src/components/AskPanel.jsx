import { useState, useEffect } from 'react';
import { Search, Loader2, X, Clock } from 'lucide-react';
import { askQuestion, diagnoseDirect } from '../api';
import VegaChart from './VegaChart';
import EvidenceChip from './EvidenceChip';
import { stripMarkdown } from '../utils';

const HISTORY_LIMIT = 8;

function historyKey(datasetId) {
  return `aiba_ask_history_${datasetId}`;
}

function loadHistory(datasetId) {
  try {
    const raw = localStorage.getItem(historyKey(datasetId));
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function saveToHistory(datasetId, question) {
  try {
    const existing = loadHistory(datasetId).filter((q) => q !== question);
    const next = [question, ...existing].slice(0, HISTORY_LIMIT);
    localStorage.setItem(historyKey(datasetId), JSON.stringify(next));
    return next;
  } catch {
    return loadHistory(datasetId);
  }
}

/**
 * Dataset-aware example questions instead of generic placeholders --
 * pulls real metric/category names out of the catalog so a first-time
 * user immediately sees what's actually askable of THEIR data, not a
 * hypothetical example that may not apply.
 */
function buildExampleQuestions(catalog) {
  if (!catalog?.tables) return [];
  const examples = [];
  for (const table of Object.values(catalog.tables)) {
    const metrics = (table.columns || []).filter((c) => c.inferred_role === 'metric');
    const categories = (table.columns || []).filter((c) => c.inferred_role === 'category');
    const dates = (table.columns || []).filter((c) => c.inferred_role === 'date');
    if (metrics.length && dates.length) {
      examples.push(`Why did ${metrics[0].name} change?`);
    }
    if (metrics.length && categories.length) {
      examples.push(`Which ${categories[0].name} has the highest ${metrics[0].name}?`);
    }
    if (metrics.length > 1) {
      examples.push(`What's the trend in ${metrics[1].name} over time?`);
    }
    if (examples.length) break; // one table's worth is enough
  }
  examples.push('What are the main metrics in this dataset, and what does each one represent?');
  return examples.slice(0, 4);
}

export default function AskPanel({ datasetId, catalog }) {
  const [question, setQuestion] = useState('');
  const [result, setResult] = useState(null);
  const [drillFilters, setDrillFilters] = useState({});
  const [loading, setLoading] = useState(false);
  const [drilling, setDrilling] = useState(false);
  const [error, setError] = useState(null);
  const [history, setHistory] = useState([]);

  useEffect(() => {
    if (datasetId) setHistory(loadHistory(datasetId));
  }, [datasetId]);

  const examples = buildExampleQuestions(catalog);

  async function runQuestion(q) {
    if (!q.trim() || !datasetId) return;
    setLoading(true);
    setError(null);
    setDrillFilters({});
    try {
      const data = await askQuestion(datasetId, q);
      setResult(data);
      setHistory(saveToHistory(datasetId, q));
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleAsk(e) {
    e.preventDefault();
    await runQuestion(question);
  }

  function askExample(q) {
    setQuestion(q);
    runQuestion(q);
  }

  async function handleDrill(datum) {
    if (!result?.findings || result.intent !== 'diagnostic') return;
    // datum.category looks like "product: Product B" -- extract dimension/value
    const match = /^(\w+):\s*(.+?)(\s*\(within.*\))?$/.exec(datum.category || '');
    if (!match) return;
    const [, dimension, value] = match;

    const newFilters = { ...drillFilters, [dimension]: value };
    setDrilling(true);
    setError(null);
    try {
      const data = await diagnoseDirect(
        datasetId,
        result.metric_column,
        result.date_column,
        newFilters
      );
      setResult((prev) => ({ ...prev, findings: data.findings, charts: data.charts }));
      setDrillFilters(newFilters);
    } catch (err) {
      setError(err.message);
    } finally {
      setDrilling(false);
    }
  }

  function clearDrill() {
    if (!result) return;
    handleAsk({ preventDefault: () => {} });
  }

  const findings = result?.findings;

  return (
    <div>
      <h2 className="font-display text-2xl text-ink mb-4">Ask</h2>

      <form onSubmit={handleAsk} className="flex gap-2 mb-6">
        <div className="relative flex-1">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Why did revenue decrease?"
            className="w-full bg-white border border-line rounded-sm pl-9 pr-3 py-2.5 text-sm text-ink placeholder:text-muted/60 focus:border-ledger-blue outline-none"
          />
        </div>
        <button
          type="submit"
          disabled={loading || !datasetId}
          className="bg-ledger-blue hover:bg-ledger-blue-light text-paper text-sm px-4 py-2.5 rounded-sm disabled:opacity-40 flex items-center gap-2"
        >
          {loading ? <Loader2 size={14} className="animate-spin" /> : null}
          Ask
        </button>
      </form>

      {error && <p className="text-sm text-decline mb-4">{error}</p>}

      {!result && !loading && (examples.length > 0 || history.length > 0) && (
        <div className="mb-6 space-y-4">
          {examples.length > 0 && (
            <div>
              <p className="text-[11px] uppercase tracking-wide text-muted mb-2">Try asking</p>
              <div className="flex flex-wrap gap-2">
                {examples.map((q) => (
                  <button
                    key={q}
                    onClick={() => askExample(q)}
                    className="text-xs bg-white border border-line rounded-sm px-3 py-1.5 text-ink hover:border-ledger-blue hover:text-ledger-blue transition-colors"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}

          {history.length > 0 && (
            <div>
              <p className="text-[11px] uppercase tracking-wide text-muted mb-2 flex items-center gap-1">
                <Clock size={11} /> Recent
              </p>
              <div className="flex flex-wrap gap-2">
                {history.map((q) => (
                  <button
                    key={q}
                    onClick={() => askExample(q)}
                    className="text-xs bg-paper-dim rounded-sm px-3 py-1.5 text-ink hover:bg-line transition-colors"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {result && (
        <div className="bg-white border border-line rounded-sm p-5 space-y-5">
          <div>
            <p className="text-[11px] uppercase tracking-wide text-muted mb-1">
              {result.intent === 'diagnostic' && 'Root-cause investigation'}
              {result.intent === 'meta' && 'About this dataset'}
              {result.intent === 'lookup' && 'Lookup'}
            </p>
            <p className="text-sm text-ink leading-relaxed">
              {stripMarkdown(result.answer)}
              {result.sql && <EvidenceChip label="SQL" detail={result.sql} />}
              {findings?.anomaly?.z_score != null && (
                <EvidenceChip
                  label={`z=${findings.anomaly.z_score}`}
                  detail={`What this means: how many standard deviations the latest period is from the historical average. ${findings.anomaly.is_notable ? 'This one is large enough (|z| > 1.0) to be a real, statistically significant shift -- not just normal noise.' : 'This is small enough to be within normal variation, not a real shift.'}\n\nRaw computation vs. historical mean/std.`}
                />
              )}
              {findings?.level1_driver && (
                <EvidenceChip
                  label={`${findings.level1_driver.contribution_pct}% contribution`}
                  detail={`What this means: how much of the total change this one category alone accounts for. It can go above 100% -- that happens when other categories partially offset it (e.g. this one dropped a lot, but something else grew a little, so this category's drop is more than the whole).\n\n${findings.level1_driver.dimension} = ${findings.level1_driver.value}\nPrevious: ${findings.level1_driver.value_prev.toLocaleString()}\nLatest: ${findings.level1_driver.value_latest.toLocaleString()}`}
                />
              )}
            </p>
          </div>

          {Object.keys(drillFilters).length > 0 && (
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-[11px] text-muted">Drilled into:</span>
              {Object.entries(drillFilters).map(([k, v]) => (
                <span key={k} className="figure text-[11px] bg-paper-dim px-2 py-0.5 rounded-sm text-ink">{k} = {v}</span>
              ))}
              <button onClick={clearDrill} className="text-[11px] text-ledger-blue flex items-center gap-0.5 hover:underline">
                <X size={11} /> reset
              </button>
              {drilling && <Loader2 size={12} className="animate-spin text-muted" />}
            </div>
          )}

          {result.charts?.trend && (
            <div>
              <VegaChart spec={result.charts.trend} />
            </div>
          )}

          {result.charts?.driver_breakdown && (
            <div>
              <p className="text-[11px] text-muted mb-1">Click a bar to drill in further</p>
              <VegaChart spec={result.charts.driver_breakdown} onMarkClick={handleDrill} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}