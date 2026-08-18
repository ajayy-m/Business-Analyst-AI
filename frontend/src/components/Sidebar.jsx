import { useState } from 'react';
import { Upload, Database, Loader2 } from 'lucide-react';
import { uploadFile } from '../api';

export default function Sidebar({ datasetId, setDatasetId, onUploaded, catalog }) {
  const [tableName, setTableName] = useState('sales');
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState(null);

  async function handleFile(e) {
    const file = e.target.files[0];
    if (!file || !datasetId || !tableName) return;
    setUploading(true);
    setError(null);
    try {
      await uploadFile(datasetId, tableName, file);
      onUploaded();
    } catch (err) {
      setError(err.message);
    } finally {
      setUploading(false);
      e.target.value = '';
    }
  }

  const tables = catalog ? Object.keys(catalog.tables || {}) : [];

  return (
    <aside className="w-72 shrink-0 bg-ink text-paper flex flex-col h-full">
      <div className="px-5 py-6 border-b border-ink-light">
        <h1 className="font-display text-xl leading-tight">AI Business<br />Analyst</h1>
        <p className="text-xs text-paper/50 mt-1">Every number, traceable.</p>
      </div>

      <div className="px-5 py-5 border-b border-ink-light">
        <label className="text-[11px] uppercase tracking-wide text-paper/50 block mb-1.5">Dataset</label>
        <input
          value={datasetId}
          onChange={(e) => setDatasetId(e.target.value.trim())}
          placeholder="e.g. demo"
          className="figure w-full bg-ink-light rounded-sm px-2.5 py-1.5 text-sm text-paper placeholder:text-paper/30 border border-transparent focus:border-ledger-blue-light outline-none"
        />
      </div>

      <div className="px-5 py-5 border-b border-ink-light space-y-3">
        <label className="text-[11px] uppercase tracking-wide text-paper/50 block">Add a table</label>
        <input
          value={tableName}
          onChange={(e) => setTableName(e.target.value.trim())}
          placeholder="table name, e.g. sales"
          className="figure w-full bg-ink-light rounded-sm px-2.5 py-1.5 text-sm text-paper placeholder:text-paper/30 border border-transparent focus:border-ledger-blue-light outline-none"
        />
        <label className="flex items-center justify-center gap-2 text-sm rounded-sm border border-dashed border-paper/25 hover:border-paper/50 transition-colors py-2.5 cursor-pointer text-paper/70 hover:text-paper">
          {uploading ? <Loader2 size={15} className="animate-spin" /> : <Upload size={15} />}
          {uploading ? 'Uploading…' : 'Upload CSV / Excel'}
          <input type="file" accept=".csv,.xlsx,.xls" className="hidden" onChange={handleFile} disabled={!datasetId || uploading} />
        </label>
        {error && <p className="text-[11px] text-decline">{error}</p>}
      </div>

      <div className="px-5 py-5 flex-1 overflow-y-auto">
        <label className="text-[11px] uppercase tracking-wide text-paper/50 flex items-center gap-1.5 mb-2">
          <Database size={12} /> Tables in this dataset
        </label>
        {tables.length === 0 && <p className="text-xs text-paper/40">No tables uploaded yet.</p>}
        <ul className="space-y-1.5">
          {tables.map((t) => (
            <li key={t} className="figure text-xs text-paper/80 bg-ink-light/60 rounded-sm px-2 py-1.5">
              {t}
              <span className="text-paper/40 ml-1.5">
                {catalog.tables[t].row_count.toLocaleString()} rows
              </span>
            </li>
          ))}
        </ul>
      </div>
    </aside>
  );
}
