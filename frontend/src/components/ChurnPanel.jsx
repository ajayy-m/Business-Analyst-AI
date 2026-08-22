import { useState, useEffect, useCallback } from 'react';
import { UserX, Loader2 } from 'lucide-react';
import { getChurn } from '../api';
import EvidenceChip from './EvidenceChip';

/**
 * Same auto-default idea as ForecastPanel: prefers an id/metric/date
 * triple that all live in the same table, since that's what the
 * backend needs to build one coherent per-customer history from.
 */
function pickDefaults(catalog) {
  const tables = catalog ? Object.values(catalog.tables || {}) : [];
  for (const t of tables) {
    const id = (t.columns || []).find((c) => c.inferred_role === 'id');
    const metric = (t.columns || []).find((c) => c.inferred_role === 'metric');
    const date = (t.columns || []).find((c) => c.inferred_role === 'date');
    if (id && metric && date) return { idCol: id.name, metricCol: metric.name, dateCol: date.name };
  }
  return { idCol: '', metricCol: '', dateCol: '' };
}

export default function ChurnPanel({ datasetId, catalog }) {
  const [idCol, setIdCol] = useState('');
  const [metricCol, setMetricCol] = useState('');
  const [dateCol, setDateCol] = useState('');
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [autoAttempted, setAutoAttempted] = useState(false);

  const columns = catalog ? Object.values(catalog.tables || {}).flatMap((t) => t.columns) : [];
  const idOptions = columns.filter((c) => c.inferred_role === 'id');
  const metricOptions = columns.filter((c) => c.inferred_role === 'metric');
  const dateOptions = columns.filter((c) => c.inferred_role === 'date');

  const runChurn = useCallback((id, metric, date) => {
    if (!id || !metric || !date || !datasetId) return;
    setLoading(true);
    setError(null);
    getChurn(datasetId, id, metric, date)
      .then(setResult)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [datasetId]);

  // auto-pick a same-table id/metric/date triple and run immediately,
  // same zero-config pattern as Dashboard/Forecast. A no-column-found
  // case (e.g. a dataset with no id-role column at all) just leaves the
  // form empty for manual selection rather than erroring.
  useEffect(() => {
    if (!catalog || autoAttempted) return;
    setAutoAttempted(true);
    const defaults = pickDefaults(catalog);
    if (defaults.idCol && defaults.metricCol && defaults.dateCol) {
      setIdCol(defaults.idCol);
      setMetricCol(defaults.metricCol);
      setDateCol(defaults.dateCol);
      runChurn(defaults.idCol, defaults.metricCol, defaults.dateCol);
    }
  }, [catalog, autoAttempted, runChurn]);

  function handleRun(e) {
    e.preventDefault();
    runChurn(idCol, metricCol, dateCol);
  }

  const weakSignal = result && result.metrics.roc_auc < 0.6;

  return (
    <div>
      <h2 className="font-display text-2xl text-ink mb-4">At-risk customers</h2>

      <form onSubmit={handleRun} className="flex gap-2 mb-6 flex-wrap items-center">
        <select value={idCol} onChange={(e) => setIdCol(e.target.value)} className="figure bg-white border border-line rounded-sm px-2.5 py-2 text-sm outline-none focus:border-ledger-blue">
          <option value="">customer id column…</option>
          {idOptions.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
        </select>
        <select value={metricCol} onChange={(e) => setMetricCol(e.target.value)} className="figure bg-white border border-line rounded-sm px-2.5 py-2 text-sm outline-none focus:border-ledger-blue">
          <option value="">metric…</option>
          {metricOptions.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
        </select>
        <select value={dateCol} onChange={(e) => setDateCol(e.target.value)} className="figure bg-white border border-line rounded-sm px-2.5 py-2 text-sm outline-none focus:border-ledger-blue">
          <option value="">date column…</option>
          {dateOptions.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
        </select>
        <button type="submit" disabled={loading || !idCol || !metricCol || !dateCol} className="bg-ledger-blue hover:bg-ledger-blue-light text-paper text-sm px-4 py-2 rounded-sm disabled:opacity-40 flex items-center gap-2">
          {loading ? <Loader2 size={14} className="animate-spin" /> : <UserX size={14} />}
          Train + score
        </button>
        <span className="text-xs text-muted">Auto-picked on load — change any dropdown to retrain on different columns</span>
      </form>

      {error && <p className="text-sm text-decline mb-4">{error}</p>}
      {loading && !result && <p className="text-sm text-muted flex items-center gap-2"><Loader2 size={14} className="animate-spin" /> Training + scoring…</p>}

      {!loading && !result && !error && autoAttempted && (!idOptions.length || !metricOptions.length || !dateOptions.length) && (
        <p className="text-sm text-muted">
          This dataset doesn't have a clear customer-ID column, so at-risk scoring can't run automatically here — pick columns above if one exists under a different name.
        </p>
      )}

      {result && (
        <div className="space-y-5">
          <div className="bg-white border border-line rounded-sm p-4 flex flex-wrap gap-x-6 gap-y-2 text-sm">
            <span>ROC AUC <EvidenceChip label={result.metrics.roc_auc} detail={`What this means: how well the model separates customers who actually churned from those who didn't, on data it never trained on. 0.5 = no better than a coin flip (no real signal). 1.0 = perfect separation.\n\nTrained on earlier period transitions, evaluated on a held-out later one it never saw during training.\nTest set: ${result.metrics.test_examples} examples, ${(result.metrics.test_churn_rate * 100).toFixed(1)}% actually churned.`} /></span>
            <span>Recall <span className="figure">{result.metrics.recall}</span></span>
            <span>Precision <span className="figure">{result.metrics.precision}</span></span>
          </div>

          {weakSignal && (
            <p className="text-xs text-flag bg-flag/10 border border-flag/30 rounded-sm px-3 py-2">
              This score is close to 0.5, which means the model isn't finding a real behavioral pattern in this data — not that anything is broken. This usually happens when the customer-ID column doesn't actually track the same person across orders (e.g. IDs assigned per transaction rather than per customer), so there's no consistent history to learn from. The list below is still ranked by the model's best guess, but treat it with proportional skepticism.
            </p>
          )}

          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wide text-muted border-b border-line">
                <th className="pb-2 font-normal">Customer</th>
                <th className="pb-2 font-normal">Churn probability</th>
                <th className="pb-2 font-normal">Recency (days)</th>
                <th className="pb-2 font-normal">Orders</th>
                <th className="pb-2 font-normal">Total spend</th>
              </tr>
            </thead>
            <tbody>
              {result.at_risk_customers.map((c) => (
                <tr key={c.customer_id} className="border-b border-line/60">
                  <td className="figure py-2">{c.customer_id}</td>
                  <td className="py-2">
                    <span className="figure text-decline">{(c.churn_probability * 100).toFixed(1)}%</span>
                  </td>
                  <td className="figure py-2 text-muted">{c.recency_days}</td>
                  <td className="figure py-2 text-muted">{c.frequency}</td>
                  <td className="figure py-2 text-muted">${c.monetary.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}