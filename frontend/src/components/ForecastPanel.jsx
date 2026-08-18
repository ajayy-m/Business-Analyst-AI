import { useState } from 'react';
import { TrendingUp, Loader2 } from 'lucide-react';
import { getForecast } from '../api';
import VegaChart from './VegaChart';
import EvidenceChip from './EvidenceChip';

export default function ForecastPanel({ datasetId, catalog }) {
  const [metricCol, setMetricCol] = useState('');
  const [dateCol, setDateCol] = useState('');
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const columns = catalog ? Object.values(catalog.tables || {}).flatMap((t) => t.columns) : [];
  const metricOptions = columns.filter((c) => c.inferred_role === 'metric');
  const dateOptions = columns.filter((c) => c.inferred_role === 'date');

  async function handleForecast(e) {
    e.preventDefault();
    if (!metricCol || !dateCol) return;
    setLoading(true);
    setError(null);
    try {
      const data = await getForecast(datasetId, metricCol, dateCol);
      setResult(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
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
      </form>

      {error && <p className="text-sm text-decline mb-4">{error}</p>}

      {result && (
        <div className="bg-white border border-line rounded-sm p-5 space-y-4">
          <p className="text-sm text-ink">
            Trend is <span className="figure">{result.trend.direction}</span>
            <EvidenceChip
              label={`R\u00b2=${result.trend.r_squared}`}
              detail={`How much of the variance the linear trend explains.\n${result.trend.r_squared < 0.3 ? 'Low -- treat this forecast with proportional skepticism.' : 'The trend explains a meaningful share of the historical variance.'}`}
            />
          </p>
          <VegaChart spec={result.chart} />
        </div>
      )}
    </div>
  );
}
