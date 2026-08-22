import { useState, useEffect, useCallback } from 'react';
import { TrendingUp, Loader2 } from 'lucide-react';
import { getForecast } from '../api';
import VegaChart from './VegaChart';
import EvidenceChip from './EvidenceChip';

/**
 * Picks a sensible default (metric, date) pair from the catalog instead
 * of leaving both selects empty -- prefers a metric and date column
 * that live in the SAME table, since that's what the backend can
 * actually resolve into one query. Falls back to the first metric/date
 * found anywhere if no single table has both.
 */
function pickDefaults(catalog) {
  const tables = catalog ? Object.values(catalog.tables || {}) : [];
  for (const t of tables) {
    const metric = (t.columns || []).find((c) => c.inferred_role === 'metric');
    const date = (t.columns || []).find((c) => c.inferred_role === 'date');
    if (metric && date) return { metricCol: metric.name, dateCol: date.name };
  }
  const allCols = tables.flatMap((t) => t.columns || []);
  const metric = allCols.find((c) => c.inferred_role === 'metric');
  const date = allCols.find((c) => c.inferred_role === 'date');
  return { metricCol: metric?.name || '', dateCol: date?.name || '' };
}

export default function ForecastPanel({ datasetId, catalog }) {
  const [metricCol, setMetricCol] = useState('');
  const [dateCol, setDateCol] = useState('');
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const columns = catalog ? Object.values(catalog.tables || {}).flatMap((t) => t.columns) : [];
  const metricOptions = columns.filter((c) => c.inferred_role === 'metric');
  const dateOptions = columns.filter((c) => c.inferred_role === 'date');

  const runForecast = useCallback((metric, date) => {
    if (!metric || !date || !datasetId) return;
    setLoading(true);
    setError(null);
    getForecast(datasetId, metric, date)
      .then(setResult)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [datasetId]);

  // auto-pick defaults and run the moment the catalog is available --
  // matches the Dashboard/Ask tabs, which never make you configure
  // before seeing anything
  useEffect(() => {
    if (!catalog) return;
    const defaults = pickDefaults(catalog);
    if (defaults.metricCol && defaults.dateCol) {
      setMetricCol(defaults.metricCol);
      setDateCol(defaults.dateCol);
      runForecast(defaults.metricCol, defaults.dateCol);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [catalog, datasetId]);

  function handleForecast(e) {
    e.preventDefault();
    runForecast(metricCol, dateCol);
  }

  return (
    <div>
      <h2 className="font-display text-2xl text-ink mb-4">Forecast</h2>

      <form onSubmit={handleForecast} className="flex gap-2 mb-6 flex-wrap items-center">
        <select value={metricCol} onChange={(e) => setMetricCol(e.target.value)} className="figure bg-white border border-line rounded-sm px-2.5 py-2 text-sm outline-none focus:border-ledger-blue">
          <option value="">metric…</option>
          {metricOptions.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
        </select>
        <select value={dateCol} onChange={(e) => setDateCol(e.target.value)} className="figure bg-white border border-line rounded-sm px-2.5 py-2 text-sm outline-none focus:border-ledger-blue">
          <option value="">date column…</option>
          {dateOptions.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
        </select>
        <button type="submit" disabled={loading || !metricCol || !dateCol} className="bg-ledger-blue hover:bg-ledger-blue-light text-paper text-sm px-4 py-2 rounded-sm disabled:opacity-40 flex items-center gap-2">
          {loading ? <Loader2 size={14} className="animate-spin" /> : <TrendingUp size={14} />}
          Project forward
        </button>
        <span className="text-xs text-muted">Auto-picked on load — change either dropdown to forecast something else</span>
      </form>

      {error && <p className="text-sm text-decline mb-4">{error}</p>}
      {loading && !result && <p className="text-sm text-muted flex items-center gap-2"><Loader2 size={14} className="animate-spin" /> Fitting trend…</p>}

      {result && (
        <div className="bg-white border border-line rounded-sm p-5 space-y-4">
          <p className="text-sm text-ink">
            Trend is <span className="figure">{result.trend.direction}</span>
            <EvidenceChip
              label={`R\u00b2=${result.trend.r_squared}`}
              detail={`How much of the variance the linear trend explains.\n${result.trend.r_squared < 0.3 ? 'Low -- treat this forecast with proportional skepticism.' : 'The trend explains a meaningful share of the historical variance.'}`}
            />
          </p>
          {result.trend.r_squared < 0.3 && (
            <p className="text-xs text-flag bg-flag/10 border border-flag/30 rounded-sm px-3 py-2">
              This forecast's trend line explains very little of the historical variation (low R²). Treat the projection as a rough guide, not a confident prediction — the underlying data doesn't show a strong, consistent trend to extrapolate from.
            </p>
          )}
          <VegaChart spec={result.chart} />
        </div>
      )}
    </div>
  );
}