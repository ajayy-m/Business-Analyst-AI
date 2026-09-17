import { useState, useEffect, useCallback } from 'react';
import { UserX, Loader2 } from 'lucide-react';
import { getChurn } from '../api';
import EvidenceChip from './EvidenceChip';

/**
 * Same idea as ForecastPanel: picks defaults strictly within one table,
 * never pooling id/metric/date across tables -- otherwise a shared
 * column name like "customer_id" across two unrelated uploads makes it
 * impossible to tell which table's history the model would actually
 * be trained on.
 */
function pickDefaults(table) {
  const cols = table?.columns || [];
  const id = cols.find((c) => c.inferred_role === 'id');
  const metric = cols.find((c) => c.inferred_role === 'metric');
  const date = cols.find((c) => c.inferred_role === 'date');
  if (id && metric && date) return { idCol: id.name, metricCol: metric.name, dateCol: date.name };
  return { idCol: '', metricCol: '', dateCol: '' };
}

export default function ChurnPanel({ datasetId, catalog }) {
  const tableNames = catalog ? Object.keys(catalog.tables || {}) : [];
  const [tableName, setTableName] = useState(tableNames[0] || '');
  const [idCol, setIdCol] = useState('');
  const [metricCol, setMetricCol] = useState('');
  const [dateCol, setDateCol] = useState('');
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [autoAttempted, setAutoAttempted] = useState(false);

  useEffect(() => {
    if (tableNames.length && !tableNames.includes(tableName)) {
      setTableName(tableNames[0]);
    }
  }, [tableNames.join(','), tableName]);

  const columns = catalog?.tables?.[tableName]?.columns || [];
  const idOptions = columns.filter((c) => c.inferred_role === 'id');
  const metricOptions = columns.filter((c) => c.inferred_role === 'metric');
  const dateOptions = columns.filter((c) => c.inferred_role === 'date');

  const runChurn = useCallback((table, id, metric, date) => {
    if (!table || !id || !metric || !date || !datasetId) return;
    setLoading(true);
    setError(null);
    getChurn(datasetId, id, metric, date, 20, table)
      .then(setResult)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [datasetId]);

  // re-pick a same-table id/metric/date triple and re-run whenever the
  // selected table changes, same zero-config pattern as
  // Dashboard/Forecast. A no-column-found case (e.g. a dataset with no
  // id-role column at all) just leaves the form empty for manual
  // selection rather than erroring.
  useEffect(() => {
    if (!catalog || !tableName) return;
    setAutoAttempted(true);
    setResult(null);
    const defaults = pickDefaults(catalog.tables?.[tableName]);
    setIdCol(defaults.idCol);
    setMetricCol(defaults.metricCol);
    setDateCol(defaults.dateCol);
    if (defaults.idCol && defaults.metricCol && defaults.dateCol) {
      runChurn(tableName, defaults.idCol, defaults.metricCol, defaults.dateCol);
    }
  }, [catalog, tableName, runChurn]);

  function handleRun(e) {
    e.preventDefault();
    runChurn(tableName, idCol, metricCol, dateCol);
  }

  const weakSignal = result && result.metrics.roc_auc < 0.6;

  return (
    <div>
      <div className="flex items-baseline justify-between mb-4 flex-wrap gap-2">
        <h2 className="font-display text-2xl text-ink">At-risk customers</h2>
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
        <span className="text-xs text-muted">Auto-picked on load — change the table, or any dropdown, to retrain on different columns</span>
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
            <span>Recall <EvidenceChip label={result.metrics.recall} detail={`What this means: of the customers who actually churned in the held-out test period, this fraction were correctly caught by the model. 1.0 = it caught every real churner (though it may also flag some who wouldn't have churned -- see Precision). 0.0 = it missed all of them.`} /></span>
            <span>Precision <EvidenceChip label={result.metrics.precision} detail={`What this means: of the customers the model flagged as likely to churn, this fraction actually did. A low number here means most flagged customers are false alarms -- worth knowing before acting on this list, e.g. by offering a retention discount to someone who wasn't actually leaving.`} /></span>
          </div>

          {weakSignal && (
            <p className="text-xs text-flag bg-flag/10 border border-flag/30 rounded-sm px-3 py-2">
              This score is close to 0.5, which means the model isn't finding a real behavioral pattern in this data — not that anything is broken. This usually happens when the customer-ID column doesn't actually track the same person across orders (e.g. IDs assigned per transaction rather than per customer), so there's no consistent history to learn from. The list below is still ranked by the model's best guess, but treat it with proportional skepticism.
            </p>
          )}

          <p className="text-xs text-muted">
            Ranked by the model's estimate, most-at-risk first — shown as a
            relative tier rather than a precise percentage, since a number
            like "92%" would overstate how confident a model this size can
            really be about one specific customer.
          </p>

          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wide text-muted border-b border-line">
                <th className="pb-2 font-normal">Customer</th>
                <th className="pb-2 font-normal">Risk</th>
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
                    <span className="text-decline">{c.risk_tier}</span>
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