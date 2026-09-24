import { useState } from 'react';
import { ShieldCheck, ChevronDown, ChevronUp } from 'lucide-react';
import { overrideColumnRole } from '../api';

const ROLES = ['date', 'metric', 'category', 'id', 'text'];

/**
 * Surfaces what ingestion already silently computes for every upload --
 * duplicate rows, blank rows dropped, columns that looked like dates but
 * couldn't be parsed, missing values -- as one clear panel instead of a
 * warnings array nobody sees. The detection already existed; this was a
 * presentation gap, not a data-quality gap.
 *
 * quality_score is a plain, explainable formula computed server-side
 * (100 minus capped penalties for missing values, duplicate rows, and
 * unparseable date columns) -- not a black-box ML score, consistent
 * with this app's "every number traceable" principle. Deliberately
 * collapsed by default: this is a diagnostic detail, not something that
 * should compete with the KPI cards for attention on a clean dataset.
 */
export default function DataQualityPanel({ dq, datasetId, tableName, columns, onCatalogChange }) {
  const [open, setOpen] = useState(false);
  const [busyCol, setBusyCol] = useState(null);
  const [roleMsg, setRoleMsg] = useState(null); // { col, ok, text }
  if (!dq) return null;

  // Corrections are refused by the backend (with the measured parse rate)
  // when the data doesn't support them -- the select just snaps back.
  async function changeRole(col, newRole) {
    setBusyCol(col);
    setRoleMsg(null);
    try {
      const res = await overrideColumnRole(datasetId, tableName, col, newRole);
      setRoleMsg({ col, ok: true, text: res.notes?.length ? res.notes.join(' ') : `'${col}' is now treated as ${newRole}.` });
      onCatalogChange?.();
    } catch (err) {
      setRoleMsg({ col, ok: false, text: err.message });
    } finally {
      setBusyCol(null);
    }
  }

  const score = dq.quality_score;
  const tone = score >= 90 ? 'text-gain' : score >= 70 ? 'text-flag' : 'text-decline';
  const toneBg = score >= 90 ? 'bg-gain/10 border-gain/30' : score >= 70 ? 'bg-flag/10 border-flag/30' : 'bg-decline/10 border-decline/30';

  const stats = [
    { label: 'Rows', value: dq.row_count.toLocaleString() },
    { label: 'Columns', value: dq.column_count.toLocaleString() },
    { label: 'Missing values', value: `${dq.missing_value_count.toLocaleString()} (${dq.missing_cell_pct}%)` },
    { label: 'Duplicate rows', value: dq.duplicate_row_count.toLocaleString() },
    { label: 'Invalid dates', value: dq.invalid_date_columns.length.toLocaleString() },
  ];

  return (
    <div className="border border-line rounded-sm mb-5 bg-white">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-4 py-2.5 text-left"
      >
        <div className="flex items-center gap-3 flex-wrap">
          <span className="flex items-center gap-1.5 text-xs uppercase tracking-wide text-muted">
            <ShieldCheck size={13} /> Data quality
          </span>
          <span className={`figure text-xs px-1.5 py-0.5 rounded-sm border ${toneBg} ${tone}`}>
            {score}%
          </span>
          <span className="figure text-xs text-muted">
            {stats.map((s) => `${s.label}: ${s.value}`).join('  ·  ')}
          </span>
        </div>
        {open ? <ChevronUp size={14} className="text-muted shrink-0" /> : <ChevronDown size={14} className="text-muted shrink-0" />}
      </button>

      {open && (
        <div className="px-4 pb-3.5 pt-1 border-t border-line">
          {dq.warnings.length === 0 ? (
            <p className="text-xs text-muted">No issues detected during upload.</p>
          ) : (
            <ul className="space-y-1">
              {dq.warnings.map((w, i) => (
                <li key={i} className="text-xs text-ink flex gap-1.5">
                  <span className="text-muted shrink-0">•</span>
                  <span>{w}</span>
                </li>
              ))}
            </ul>
          )}
          {columns && columns.length > 0 && (
            <div className="mt-3 pt-3 border-t border-line">
              <p className="text-xs uppercase tracking-wide text-muted mb-1.5">Column roles</p>
              <p className="text-[11px] text-muted mb-2">
                Auto-detected. If one is wrong, correct it -- date and metric changes re-parse the
                column and are refused if the values don't actually convert.
              </p>
              <div className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-1 items-center">
                {columns.map((c) => (
                  <div key={c.name} className="contents">
                    <span className="figure text-xs text-ink truncate" title={c.name}>
                      {c.name}
                      <span className="text-muted"> · {c.sample_values?.[0] ?? ''}</span>
                    </span>
                    <select
                      value={c.inferred_role}
                      disabled={busyCol === c.name}
                      onChange={(e) => changeRole(c.name, e.target.value)}
                      className="text-xs border border-line rounded-sm bg-white px-1.5 py-0.5"
                    >
                      {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                    </select>
                  </div>
                ))}
              </div>
              {roleMsg && (
                <p className={`text-xs mt-2 ${roleMsg.ok ? 'text-gain' : 'text-decline'}`}>{roleMsg.text}</p>
              )}
            </div>
          )}
          <p className="text-[11px] text-muted mt-2.5">
            Score is 100 minus capped penalties for missing values, duplicate
            rows, and columns that looked like dates but couldn't be parsed
            reliably -- a fixed formula, not a model's guess.
          </p>
        </div>
      )}
    </div>
  );
}