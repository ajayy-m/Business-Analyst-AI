import { useEffect, useState, useCallback } from 'react';
import { TrendingUp, TrendingDown, Loader2, X } from 'lucide-react';
import { getDashboard } from '../api';
import { humanize } from '../utils';
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
 * Tableau-style filter bar: one dropdown per detected category column
 * (populated from the backend's filter metadata, never hardcoded),
 * plus a date range if the table has a date column. Changing any of
 * these re-requests the whole dashboard from the backend, which
 * recomputes every KPI and chart server-side -- the frontend never
 * re-derives aggregates from raw rows itself.
 */
function FilterBar({ filterMeta, activeFilters, onChange, dateFrom, dateTo, onDateChange, onClear }) {
  const hasActive = Object.keys(activeFilters).length > 0 || dateFrom || dateTo;

  return (
    <div className="flex flex-wrap items-center gap-2 mb-5 pb-4 border-b border-line">
      {(filterMeta?.categorical || []).map((f) => (
        <select
          key={f.column}
          value={activeFilters[f.column] || ''}
          onChange={(e) => onChange(f.column, e.target.value || null)}
          className={`figure text-xs border rounded-sm px-2 py-1.5 outline-none focus:border-ledger-blue ${
            activeFilters[f.column] ? 'bg-ledger-blue text-paper border-ledger-blue' : 'bg-white border-line text-ink'
          }`}
        >
          <option value="">{humanize(f.column)}: all</option>
          {f.values.map((v) => <option key={v} value={v}>{v}</option>)}
        </select>
      ))}

      {filterMeta?.date && (
        <div className="flex items-center gap-1.5 text-xs">
          <span className="text-muted">{humanize(filterMeta.date.column)}:</span>
          <input
            type="date"
            value={dateFrom || ''}
            min={filterMeta.date.min}
            max={filterMeta.date.max}
            onChange={(e) => onDateChange(e.target.value || null, dateTo)}
            className="figure border border-line rounded-sm px-1.5 py-1 outline-none focus:border-ledger-blue"
          />
          <span className="text-muted">to</span>
          <input
            type="date"
            value={dateTo || ''}
            min={filterMeta.date.min}
            max={filterMeta.date.max}
            onChange={(e) => onDateChange(dateFrom, e.target.value || null)}
            className="figure border border-line rounded-sm px-1.5 py-1 outline-none focus:border-ledger-blue"
          />
        </div>
      )}

      {hasActive && (
        <button onClick={onClear} className="flex items-center gap-1 text-xs text-muted hover:text-decline ml-1">
          <X size={12} /> Clear filters
        </button>
      )}
    </div>
  );
}

/**
 * Auto-generated summary dashboard: fetches the composed KPI + chart
 * set the moment data exists, with no question asked. Chart selection
 * and type are entirely decided server-side by dashboard_composer.py
 * -- this component lays out whatever it's given, plus the filter bar
 * that drives which slice of the data that composition runs against.
 */
export default function Dashboard({ datasetId, catalog }) {
  const tableNames = catalog ? Object.keys(catalog.tables || {}) : [];
  const [tableName, setTableName] = useState(tableNames[0] || '');
  const [dashboard, setDashboard] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [activeFilters, setActiveFilters] = useState({});
  const [dateFrom, setDateFrom] = useState(null);
  const [dateTo, setDateTo] = useState(null);

  useEffect(() => {
    if (tableNames.length && !tableNames.includes(tableName)) {
      setTableName(tableNames[0]);
    }
  }, [tableNames.join(','), tableName]);

  // switching tables should reset filters -- they belong to the old table's columns
  useEffect(() => {
    setActiveFilters({});
    setDateFrom(null);
    setDateTo(null);
  }, [tableName]);

  const refresh = useCallback(() => {
    if (!datasetId || !tableName) return;
    setLoading(true);
    setError(null);
    getDashboard(datasetId, tableName, { filters: activeFilters, dateFrom, dateTo })
      .then(setDashboard)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [datasetId, tableName, activeFilters, dateFrom, dateTo]);

  useEffect(() => { refresh(); }, [refresh]);

  function handleFilterChange(column, value) {
    setActiveFilters((prev) => {
      const next = { ...prev };
      if (value) next[column] = value; else delete next[column];
      return next;
    });
  }

  function handleDateChange(from, to) {
    setDateFrom(from);
    setDateTo(to);
  }

  function clearFilters() {
    setActiveFilters({});
    setDateFrom(null);
    setDateTo(null);
  }

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

      {dashboard?.filters && (dashboard.filters.categorical?.length > 0 || dashboard.filters.date) && (
        <FilterBar
          filterMeta={dashboard.filters}
          activeFilters={activeFilters}
          onChange={handleFilterChange}
          dateFrom={dateFrom}
          dateTo={dateTo}
          onDateChange={handleDateChange}
          onClear={clearFilters}
        />
      )}

      {loading && <p className="text-sm text-muted flex items-center gap-2"><Loader2 size={14} className="animate-spin" /> Analyzing…</p>}
      {error && <p className="text-sm text-decline">{error}</p>}
      {dashboard?.note && <p className="text-sm text-muted">{dashboard.note}</p>}

      {dashboard?.kpis?.length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
          {dashboard.kpis.map((k) => <KpiCard key={k.metric} kpi={k} />)}
        </div>
      )}

      {dashboard?.kpis?.length === 0 && !dashboard?.note && !loading && (
        <p className="text-sm text-muted mb-6">No data remains for the current filter selection.</p>
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