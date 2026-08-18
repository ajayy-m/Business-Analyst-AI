import { useState } from 'react';
import { Search, Loader2, X } from 'lucide-react';
import { askQuestion, diagnoseDirect } from '../api';
import VegaChart from './VegaChart';
import EvidenceChip from './EvidenceChip';
import { stripMarkdown } from '../utils';

export default function AskPanel({ datasetId }) {
  const [question, setQuestion] = useState('');
  const [result, setResult] = useState(null);
  const [drillFilters, setDrillFilters] = useState({});
  const [loading, setLoading] = useState(false);
  const [drilling, setDrilling] = useState(false);
  const [error, setError] = useState(null);

  async function handleAsk(e) {
    e.preventDefault();
    if (!question.trim() || !datasetId) return;
    setLoading(true);
    setError(null);
    setDrillFilters({});
    try {
      const data = await askQuestion(datasetId, question);
      setResult(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleDrill(datum) {
    if (!result?.findings || result.intent !== 'diagnostic') return;
    // datum.category looks like "product: Product B" -- extract dimension/value
    const match = /^(\w+):\s*(.+?)(\s*\(within.*\))?$/.exec(datum.category || '');
    if (!match) return;
    const [, dimension, value] = match;

    const newFilters = { ...drillFilters, [dimension]: value };
    setDrilling(true);
    setError(null);
    try {
      const data = await diagnoseDirect(
        datasetId,
        result.metric_column,
        result.date_column,
        newFilters
      );
      setResult((prev) => ({ ...prev, findings: data.findings, charts: data.charts }));
      setDrillFilters(newFilters);
    } catch (err) {
      setError(err.message);
    } finally {
      setDrilling(false);
    }
  }

  function clearDrill() {
    if (!result) return;
    handleAsk({ preventDefault: () => {} });
  }

  const findings = result?.findings;

  return (
    <div>
      <h2 className="font-display text-2xl text-ink mb-4">Ask</h2>

      <form onSubmit={handleAsk} className="flex gap-2 mb-6">
        <div className="relative flex-1">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Why did revenue decrease?"
            className="w-full bg-white border border-line rounded-sm pl-9 pr-3 py-2.5 text-sm text-ink placeholder:text-muted/60 focus:border-ledger-blue outline-none"
          />
        </div>
        <button
          type="submit"
          disabled={loading || !datasetId}
          className="bg-ledger-blue hover:bg-ledger-blue-light text-paper text-sm px-4 py-2.5 rounded-sm disabled:opacity-40 flex items-center gap-2"
        >
          {loading ? <Loader2 size={14} className="animate-spin" /> : null}
          Ask
        </button>
      </form>

      {error && <p className="text-sm text-decline mb-4">{error}</p>}

      {result && (
        <div className="bg-white border border-line rounded-sm p-5 space-y-5">
          <div>
            <p className="text-[11px] uppercase tracking-wide text-muted mb-1">
              {result.intent === 'diagnostic' ? 'Root-cause investigation' : 'Lookup'}
            </p>
            <p className="text-sm text-ink leading-relaxed">
              {stripMarkdown(result.answer)}
              {result.sql && <EvidenceChip label="SQL" detail={result.sql} />}
              {findings?.anomaly?.z_score != null && (
                <EvidenceChip
                  label={`z=${findings.anomaly.z_score}`}
                  detail={`Deviation z-score vs. historical mean/std.\n${findings.anomaly.is_notable ? 'Statistically notable (|z| > 1.0).' : 'Within normal variation.'}`}
                />
              )}
              {findings?.level1_driver && (
                <EvidenceChip
                  label={`${findings.level1_driver.contribution_pct}% contribution`}
                  detail={`${findings.level1_driver.dimension} = ${findings.level1_driver.value}\nPrevious: ${findings.level1_driver.value_prev.toLocaleString()}\nLatest: ${findings.level1_driver.value_latest.toLocaleString()}`}
                />
              )}
            </p>
          </div>

          {Object.keys(drillFilters).length > 0 && (
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-[11px] text-muted">Drilled into:</span>
              {Object.entries(drillFilters).map(([k, v]) => (
                <span key={k} className="figure text-[11px] bg-paper-dim px-2 py-0.5 rounded-sm text-ink">{k} = {v}</span>
              ))}
              <button onClick={clearDrill} className="text-[11px] text-ledger-blue flex items-center gap-0.5 hover:underline">
                <X size={11} /> reset
              </button>
              {drilling && <Loader2 size={12} className="animate-spin text-muted" />}
            </div>
          )}

          {result.charts?.trend && (
            <div>
              <VegaChart spec={result.charts.trend} />
            </div>
          )}

          {result.charts?.driver_breakdown && (
            <div>
              <p className="text-[11px] text-muted mb-1">Click a bar to drill in further</p>
              <VegaChart spec={result.charts.driver_breakdown} onMarkClick={handleDrill} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}