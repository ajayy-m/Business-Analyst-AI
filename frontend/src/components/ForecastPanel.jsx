import { useState, useEffect, useCallback } from 'react';
import { TrendingUp, Loader2 } from 'lucide-react';
import { getForecast } from '../api';
import VegaChart from './VegaChart';
import EvidenceChip from './EvidenceChip';

/**
 * Picks a sensible default (metric, date) pair within a single table --
 * deliberately never pools columns across tables, since two unrelated
 * uploaded tables routinely share a column name (e.g. two files both
 * having "revenue"/"order_date"), and there's no way to tell which
 * table the person meant once the names are merged into one list.
 */
function pickDefaults(table) {
  const cols = table?.columns || [];
  const metric = cols.find((c) => c.inferred_role === 'metric');
  const date = cols.find((c) => c.inferred_role === 'date');
  return { metricCol: metric?.name || '', dateCol: date?.name || '' };
}

export default function ForecastPanel({ datasetId, catalog }) {
  const tableNames = catalog ? Object.keys(catalog.tables || {}) : [];
  const [tableName, setTableName] = useState(tableNames[0] || '');
  const [metricCol, setMetricCol] = useState('');
  const [dateCol, setDateCol] = useState('');
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (tableNames.length && !tableNames.includes(tableName)) {
      setTableName(tableNames[0]);
    }
  }, [tableNames.join(','), tableName]);

  const columns = catalog?.tables?.[tableName]?.columns || [];
  const metricOptions = columns.filter((c) => c.inferred_role === 'metric');
  const dateOptions = columns.filter((c) => c.inferred_role === 'date');

  const runForecast = useCallback((table, metric, date) => {
    if (!table || !metric || !date || !datasetId) return;
    setLoading(true);
    setError(null);
    getForecast(datasetId, metric, date, 3, 'month', table)
      .then(setResult)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [datasetId]);

  // re-pick defaults and re-run whenever the selected table changes --
  // matches the Dashboard/Ask tabs, which never make you configure
  // before seeing anything
  useEffect(() => {
    if (!catalog || !tableName) return;
    const defaults = pickDefaults(catalog.tables?.[tableName]);
    setMetricCol(defaults.metricCol);
    setDateCol(defaults.dateCol);
    setResult(null);
    if (defaults.metricCol && defaults.dateCol) {
      runForecast(tableName, defaults.metricCol, defaults.dateCol);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [catalog, tableName]);

  function handleForecast(e) {
    e.preventDefault();
    runForecast(tableName, metricCol, dateCol);
  }

  return (
    <div>
      <div className="flex items-baseline justify-between mb-4 flex-wrap gap-2">
        <h2 className="font-display text-2xl text-ink">Forecast</h2>
        {tableNames.length > 1 && (
          <select
            value={tableName}
            onChange={(e) => setTableName(e.target.value)}
            className="figure bg-white border border-line rounded-sm px-2 py-1.5 text-xs outline-none focus:border-ledger-blue"
          >
            {tableNames.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        )}
      </div>

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
        <span className="text-xs text-muted">Auto-picked on load — change either dropdown, or the table, to forecast something else</span>
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