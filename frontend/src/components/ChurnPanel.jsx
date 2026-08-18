import { useState } from 'react';
import { UserX, Loader2 } from 'lucide-react';
import { getChurn } from '../api';
import EvidenceChip from './EvidenceChip';

export default function ChurnPanel({ datasetId, catalog }) {
  const [idCol, setIdCol] = useState('');
  const [metricCol, setMetricCol] = useState('');
  const [dateCol, setDateCol] = useState('');
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const columns = catalog ? Object.values(catalog.tables || {}).flatMap((t) => t.columns) : [];
  const idOptions = columns.filter((c) => c.inferred_role === 'id');
  const metricOptions = columns.filter((c) => c.inferred_role === 'metric');
  const dateOptions = columns.filter((c) => c.inferred_role === 'date');

  async function handleRun(e) {
    e.preventDefault();
    if (!idCol || !metricCol || !dateCol) return;
    setLoading(true);
    setError(null);
    try {
      const data = await getChurn(datasetId, idCol, metricCol, dateCol);
      setResult(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

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
      </form>

      {error && <p className="text-sm text-decline mb-4">{error}</p>}

      {result && (
        <div className="space-y-5">
          <div className="bg-white border border-line rounded-sm p-4 flex flex-wrap gap-x-6 gap-y-2 text-sm">
            <span>ROC AUC <EvidenceChip label={result.metrics.roc_auc} detail={`Trained on earlier period transitions, evaluated on a held-out later one it never saw during training.\nTest set: ${result.metrics.test_examples} examples, ${(result.metrics.test_churn_rate * 100).toFixed(1)}% actually churned.`} /></span>
            <span>Recall <span className="figure">{result.metrics.recall}</span></span>
            <span>Precision <span className="figure">{result.metrics.precision}</span></span>
          </div>

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
