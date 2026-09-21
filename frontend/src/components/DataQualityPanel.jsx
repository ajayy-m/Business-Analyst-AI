import { useState } from 'react';
import { ShieldCheck, ChevronDown, ChevronUp } from 'lucide-react';

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
export default function DataQualityPanel({ dq }) {
  const [open, setOpen] = useState(false);
  if (!dq) return null;

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