import { useEffect, useState } from 'react';
import { AlertTriangle, Loader2 } from 'lucide-react';
import { getAnomalies } from '../api';

export default function Dashboard({ datasetId }) {
  const [flags, setFlags] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!datasetId) return;
    setLoading(true);
    setError(null);
    getAnomalies(datasetId)
      .then((data) => setFlags(data.flags))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [datasetId]);

  return (
    <div>
      <div className="flex items-baseline justify-between mb-4">
        <h2 className="font-display text-2xl text-ink">What looks off</h2>
        <p className="text-xs text-muted">Proactive scan · every metric × dimension, z-score &gt; 1.5</p>
      </div>

      {loading && <p className="text-sm text-muted flex items-center gap-2"><Loader2 size={14} className="animate-spin" /> Scanning…</p>}
      {error && <p className="text-sm text-decline">{error}</p>}
      {flags && flags.length === 0 && <p className="text-sm text-muted">No statistically notable deviations found.</p>}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {flags?.map((f, i) => (
          <div key={i} className="bg-white border border-line rounded-sm px-4 py-3 flex items-start gap-3">
            <AlertTriangle size={16} className={Math.abs(f.z_score) > 3 ? 'text-decline shrink-0 mt-0.5' : 'text-flag shrink-0 mt-0.5'} />
            <div className="min-w-0">
              <p className="text-sm text-ink">
                <span className="figure font-medium">{f.metric}</span>
                {f.dimension && (
                  <span className="text-muted"> · {f.dimension} = <span className="figure">{f.category}</span></span>
                )}
              </p>
              <p className="text-xs text-muted mt-0.5">
                <span className="figure">{f.period?.slice(0, 10)}</span> · value <span className="figure">{f.value.toLocaleString()}</span>
              </p>
            </div>
            <span className={`figure ml-auto text-xs shrink-0 ${Math.abs(f.z_score) > 3 ? 'text-decline' : 'text-flag'}`}>
              z={f.z_score}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
