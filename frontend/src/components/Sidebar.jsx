import { useState, useCallback } from 'react';
import { Upload, Database, Loader2, CheckCircle2, XCircle } from 'lucide-react';
import { uploadFile } from '../api';
import { humanize, uniqueTableName } from '../utils';

/**
 * No dataset field, no table-name field. The person just drops one or
 * more files onto the zone; each one is auto-named from its filename
 * and uploaded immediately. `datasetId` is still passed in as a prop
 * (it's the hidden workspace ID from getWorkspaceId()), but there's
 * nothing in this component for the person to read or type about it.
 */
export default function Sidebar({ datasetId, onUploaded, catalog }) {
  const [dragActive, setDragActive] = useState(false);
  // status per filename while a batch is in flight: 'uploading' | 'done' | 'error'
  const [uploadStatus, setUploadStatus] = useState({});

  const existingTableNames = catalog ? Object.keys(catalog.tables || {}) : [];

  const handleFiles = useCallback(
    async (fileList) => {
      const files = Array.from(fileList).filter((f) =>
        /\.(csv|xlsx|xls)$/i.test(f.name)
      );
      if (!files.length || !datasetId) return;

      // Reserve unique names up front so two files dropped in the same
      // batch (e.g. two exports both called "data.csv") don't collide
      // with each other, not just with what's already in the catalog.
      const namesInUse = [...existingTableNames];
      const jobs = files.map((file) => {
        const tableName = uniqueTableName(file.name, namesInUse);
        namesInUse.push(tableName);
        return { file, tableName };
      });

      setUploadStatus((s) => {
        const next = { ...s };
        jobs.forEach(({ file }) => { next[file.name] = 'uploading'; });
        return next;
      });

      for (const { file, tableName } of jobs) {
        try {
          await uploadFile(datasetId, tableName, file);
          setUploadStatus((s) => ({ ...s, [file.name]: 'done' }));
          onUploaded();
        } catch (err) {
          setUploadStatus((s) => ({ ...s, [file.name]: 'error' }));
        }
      }
    },
    [datasetId, existingTableNames, onUploaded]
  );

  function onDrop(e) {
    e.preventDefault();
    setDragActive(false);
    handleFiles(e.dataTransfer.files);
  }

  function onBrowse(e) {
    handleFiles(e.target.files);
    e.target.value = '';
  }

  const pending = Object.entries(uploadStatus).filter(([, s]) => s === 'uploading');
  const tables = catalog ? Object.keys(catalog.tables || {}) : [];

  return (
    <aside className="w-72 shrink-0 bg-ink text-paper flex flex-col h-full">
      <div className="px-5 py-6 border-b border-ink-light">
        <h1 className="font-display text-xl leading-tight">AI Business<br />Analyst</h1>
        <p className="text-xs text-paper/50 mt-1">Every number, traceable.</p>
      </div>

      <div className="px-5 py-5 border-b border-ink-light">
        <label
          onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
          onDragLeave={() => setDragActive(false)}
          onDrop={onDrop}
          className={`flex flex-col items-center justify-center gap-1.5 text-center text-sm rounded-sm border border-dashed transition-colors py-6 px-3 cursor-pointer ${
            dragActive
              ? 'border-ledger-blue-light bg-ink-light text-paper'
              : 'border-paper/25 hover:border-paper/50 text-paper/70 hover:text-paper'
          }`}
        >
          <Upload size={18} />
          <span>Drop your data here</span>
          <span className="text-[11px] text-paper/40">or click to browse — CSV or Excel, any number of files</span>
          <input
            type="file"
            accept=".csv,.xlsx,.xls"
            multiple
            className="hidden"
            onChange={onBrowse}
            disabled={!datasetId}
          />
        </label>

        {pending.length > 0 && (
          <p className="text-[11px] text-paper/50 mt-2 flex items-center gap-1.5">
            <Loader2 size={11} className="animate-spin" /> Analyzing {pending.length} file{pending.length > 1 ? 's' : ''}…
          </p>
        )}
        {Object.entries(uploadStatus)
          .filter(([, s]) => s === 'error')
          .map(([name]) => (
            <p key={name} className="text-[11px] text-decline mt-1.5 flex items-center gap-1.5">
              <XCircle size={11} /> Couldn't process {name}
            </p>
          ))}
      </div>

      <div className="px-5 py-5 flex-1 overflow-y-auto">
        <label className="text-[11px] uppercase tracking-wide text-paper/50 flex items-center gap-1.5 mb-2">
          <Database size={12} /> Your data
        </label>
        {tables.length === 0 && (
          <p className="text-xs text-paper/40">Nothing uploaded yet — drop a file above to get started.</p>
        )}
        <ul className="space-y-1.5">
          {tables.map((t) => (
            <li key={t} className="text-xs text-paper/80 bg-ink-light/60 rounded-sm px-2 py-1.5 flex items-center justify-between gap-2">
              <span className="truncate">{humanize(t)}</span>
              <span className="figure text-paper/40 shrink-0 flex items-center gap-1">
                {uploadStatus[t] !== 'error' && <CheckCircle2 size={11} className="text-gain" />}
                {catalog.tables[t].row_count.toLocaleString()} rows
              </span>
            </li>
          ))}
        </ul>
      </div>
    </aside>
  );
}