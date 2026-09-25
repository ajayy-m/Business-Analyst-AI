import { useState, useEffect, useCallback } from 'react';
import { AlertTriangle, Loader2 } from 'lucide-react';
import { getAnomalies } from '../api';
import EvidenceChip from './EvidenceChip';

const THRESHOLDS = [
  { value: 1, label: 'More flags (z > 1.0)' },
  { value: 1.5, label: 'Default (z > 1.5)' },
  { value: 2, label: 'Fewer, stronger flags (z > 2.0)' },
];

/**
 * Breadth-first companion to Ask's depth-first drill-down: instead of
 * answering one question well, this scans every metric x category
 * combination in the selected table and surfaces whichever ones moved
 * further from their own recent history than chance would predict.
 * Same z-score machinery as ChurnPanel's evidence, just run broadly.
 */
export default function AnomalyPanel({ datasetId, catalog, selectedTable, onSelectTable }) {
  const tableNames = catalog ? Object.keys(catalog.tables || {}) : [];
  const tableName = selectedTable;
  const [zThreshold, setZThreshold] = useState(1.5);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const columns = catalog?.tables?.[tableName]?.columns || [];
  const hasMetric = columns.some((c) => c.inferred_role === 'metric');
  const hasDate = columns.some((c) => c.inferred_role === 'date');

  const run = useCallback((table, threshold) => {
    if (!table || !datasetId) return;
    setLoading(true);
    setError(null);
    getAnomalies(datasetId, table, threshold)
      .then(setResult)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [datasetId]);

  // Re-scan whenever the table changes, same zero-config pattern as the
  // other tabs -- scanning is cheap (it's just grouped aggregates), so
  // there's no reason to make the person click a button first.
  useEffect(() => {
    if (!catalog || !tableName) return;
    setResult(null);
    run(tableName, zThreshold);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [catalog, tableName]);

  function handleThresholdChange(e) {
    const t = Number(e.target.value);
    setZThreshold(t);
    run(tableName, t);
  }

  return (
    <div>
      <div className="flex items-baseline justify-between mb-4 flex-wrap gap-2">
        <h2 className="font-display text-2xl text-ink">Anomalies</h2>
        {tableNames.length > 1 && (
          <select
            value={tableName || ''}
            onChange={(e) => onSelectTable(e.target.value)}
            className="figure bg-white border border-line rounded-sm px-2 py-1.5 text-xs outline-none focus:border-ledger-blue"
          >
            {tableNames.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        )}
      </div>

      <div className="flex gap-2 mb-6 flex-wrap items-center">
        <select
          value={zThreshold}
          onChange={handleThresholdChange}
          disabled={loading}
          className="figure bg-white border border-line rounded-sm px-2.5 py-2 text-sm outline-none focus:border-ledger-blue"
        >
          {THRESHOLDS.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
        </select>
        <span className="text-xs text-muted">
          Scans every metric, and every metric split by each category column, for the latest
          period's value sitting further from its own history than this z-score.
        </span>
      </div>

      {error && <p className="text-sm text-decline mb-4">{error}</p>}
      {loading && !result && (
        <p className="text-sm text-muted flex items-center gap-2">
          <Loader2 size={14} className="animate-spin" /> Scanning…
        </p>
      )}

      {!loading && !error && !hasMetric && (
        <p className="text-sm text-muted">
          This table has no metric column, so there's nothing numeric to scan for anomalies.
        </p>
      )}
      {!loading && !error && hasMetric && !hasDate && (
        <p className="text-sm text-muted">
          This table has no date column, so there's no history to compare the latest period
          against. Set one under Data quality → Column roles on the Dashboard tab.
        </p>
      )}

      {!loading && !error && hasMetric && hasDate && result && result.flags.length === 0 && (
        <p className="text-sm text-muted">
          Nothing crossed the z {'>'} {zThreshold} threshold — every metric's latest period is
          within its normal range. Try a lower threshold above to see softer signals.
        </p>
      )}

      {result && result.flags.length > 0 && (
        <div className="space-y-3">
          <p className="text-xs text-muted">
            {result.count} flag{result.count === 1 ? '' : 's'}, strongest deviation first.
          </p>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wide text-muted border-b border-line">
                <th className="py-2 pr-4 font-normal">Metric</th>
                <th className="py-2 pr-4 font-normal">Where</th>
                <th className="py-2 pr-4 font-normal">Period</th>
                <th className="py-2 pr-4 font-normal text-right">Value</th>
                <th className="py-2 pr-4 font-normal text-right">Z-score</th>
              </tr>
            </thead>
            <tbody>
              {result.flags.map((f, i) => (
                <tr key={i} className="border-b border-line/60">
                  <td className="figure py-2 pr-4 text-ink">{f.metric}</td>
                  <td className="py-2 pr-4 text-ink">
                    {f.dimension ? (
                      <>
                        <span className="text-muted">{f.dimension} = </span>
                        {f.category}
                      </>
                    ) : (
                      <span className="text-muted">Overall</span>
                    )}
                  </td>
                  <td className="figure py-2 pr-4 text-muted">{f.period}</td>
                  <td className="figure py-2 pr-4 text-ink text-right">{f.value.toLocaleString()}</td>
                  <td className="py-2 pr-4 text-right">
                    <EvidenceChip
                      align="right"
                      label={
                        <span className={`flex items-center gap-1 ${f.z_score > 0 ? 'text-gain' : 'text-decline'}`}>
                          <AlertTriangle size={11} />
                          {f.z_score > 0 ? '+' : ''}{f.z_score}
                        </span>
                      }
                      detail={`What this means: how many standard deviations this quarter's ${f.metric}${f.dimension ? ` (${f.dimension} = ${f.category})` : ''} sits from its own historical average across prior quarters. ${f.z_score > 0 ? 'Positive = notably higher than usual.' : 'Negative = notably lower than usual.'} This flags a statistical deviation, not a cause -- worth checking what changed in ${f.period} before acting on it.`}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}