import { useEffect, useState } from 'react';
import { TrendingUp, TrendingDown, Loader2 } from 'lucide-react';
import { getDashboard } from '../api';
import VegaChart from './VegaChart';

function KpiCard({ kpi }) {
  const up = kpi.trend === 'up';
  return (
    <div className="bg-white border border-line rounded-sm px-4 py-3">
      <p className="text-xs text-muted uppercase tracking-wide">{kpi.label}</p>
      <p className="figure text-2xl text-ink mt-1">{kpi.current_value.toLocaleString()}</p>
      <div className="flex items-center gap-1.5 mt-1">
        {up ? <TrendingUp size={13} className="text-gain" /> : <TrendingDown size={13} className="text-decline" />}
        <span className={`figure text-xs ${up ? 'text-gain' : 'text-decline'}`}>
          {kpi.pct_change === null ? '—' : `${kpi.pct_change > 0 ? '+' : ''}${kpi.pct_change}%`}
        </span>
        <span className="text-xs text-muted">vs. previous · {kpi.period_label?.slice(0, 10)}</span>
      </div>
    </div>
  );
}

/**
 * Auto-generated summary dashboard: fetches the composed KPI + chart
 * set the moment data exists, with no question asked. Chart selection
 * and type are entirely decided server-side by dashboard_composer.py
 * -- this component just lays out whatever it's given.
 */
export default function Dashboard({ datasetId, catalog }) {
  const tableNames = catalog ? Object.keys(catalog.tables || {}) : [];
  const [tableName, setTableName] = useState(tableNames[0] || '');
  const [dashboard, setDashboard] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // keep the selected table valid as the catalog changes (e.g. after
  // a new upload) without wiping a still-valid selection
  useEffect(() => {
    if (tableNames.length && !tableNames.includes(tableName)) {
      setTableName(tableNames[0]);
    }
  }, [tableNames.join(','), tableName]);

  useEffect(() => {
    if (!datasetId || !tableName) return;
    setLoading(true);
    setError(null);
    getDashboard(datasetId, tableName)
      .then(setDashboard)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [datasetId, tableName]);

  return (
    <div>
      <div className="flex items-baseline justify-between mb-4 flex-wrap gap-2">
        <h2 className="font-display text-2xl text-ink">Dashboard</h2>
        <div className="flex items-center gap-2">
          {tableNames.length > 1 && (
            <select
              value={tableName}
              onChange={(e) => setTableName(e.target.value)}
              className="figure bg-white border border-line rounded-sm px-2 py-1.5 text-xs outline-none focus:border-ledger-blue"
            >
              {tableNames.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          )}
          <p className="text-xs text-muted">Auto-generated · every number computed, none guessed</p>
        </div>
      </div>

      {loading && <p className="text-sm text-muted flex items-center gap-2"><Loader2 size={14} className="animate-spin" /> Analyzing…</p>}
      {error && <p className="text-sm text-decline">{error}</p>}
      {dashboard?.note && <p className="text-sm text-muted">{dashboard.note}</p>}

      {dashboard?.kpis?.length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
          {dashboard.kpis.map((k) => <KpiCard key={k.metric} kpi={k} />)}
        </div>
      )}

      {dashboard?.charts?.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {dashboard.charts.map((c, i) => (
            <div key={i} className="bg-white border border-line rounded-sm p-4 overflow-x-auto">
              <VegaChart spec={c.spec} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}