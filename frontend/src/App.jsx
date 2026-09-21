import { useState, useEffect, useCallback } from 'react';
import { LayoutDashboard, Search, TrendingUp, UserX } from 'lucide-react';
import Sidebar from './components/Sidebar';
import Dashboard from './components/Dashboard';
import AskPanel from './components/AskPanel';
import ForecastPanel from './components/ForecastPanel';
import ChurnPanel from './components/ChurnPanel';
import { getCatalog } from './api';
import { getWorkspaceId } from './utils';

const TABS = [
  { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { id: 'ask', label: 'Ask', icon: Search },
  { id: 'forecast', label: 'Forecast', icon: TrendingUp },
  { id: 'churn', label: 'At-risk', icon: UserX },
];

export default function App() {
  // Silent, persistent per-browser workspace -- never surfaced as a
  // field the person fills in. Read once on mount.
  const [datasetId] = useState(getWorkspaceId);
  const [catalog, setCatalog] = useState(null);
  const [tab, setTab] = useState('dashboard');

  // The one shared "which dataset am I looking at" selection, used by
  // every tab (Dashboard/Ask/Forecast/At-risk) and by the sidebar's
  // own highlight. Previously each tab kept its own independent local
  // selection that defaulted back to whichever table was uploaded
  // first every time the tab remounted -- so picking a dataset in one
  // tab, then switching tabs, silently reverted to the first upload
  // ("Sample Sales") instead of staying on what you'd actually
  // selected. Lifting it here makes it a single source of truth.
  const [selectedTable, setSelectedTable] = useState(null);

  const refreshCatalog = useCallback(() => {
    if (!datasetId) return;
    getCatalog(datasetId)
      .then(setCatalog)
      .catch(() => setCatalog(null));
  }, [datasetId]);

  useEffect(() => {
    refreshCatalog();
  }, [refreshCatalog]);

  // Keep selectedTable valid as the catalog loads/changes: pick the
  // first table the first time data appears, and re-pick if whatever
  // was selected no longer exists (e.g. this browser's workspace was
  // reset). Otherwise leave the person's choice alone -- this must NOT
  // reset every time the catalog object is a new reference (e.g. after
  // any upload), or picking a table would immediately snap back.
  useEffect(() => {
    const tableNames = catalog ? Object.keys(catalog.tables || {}) : [];
    if (tableNames.length === 0) {
      if (selectedTable !== null) setSelectedTable(null);
      return;
    }
    if (!selectedTable || !tableNames.includes(selectedTable)) {
      setSelectedTable(tableNames[0]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [catalog]);

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar
        datasetId={datasetId}
        onUploaded={refreshCatalog}
        catalog={catalog}
        selectedTable={selectedTable}
        onSelectTable={setSelectedTable}
      />

      <main className="flex-1 flex flex-col overflow-hidden">
        <nav className="flex gap-1 px-6 pt-5 border-b border-line bg-paper">
          {TABS.map((t) => {
            const Icon = t.icon;
            const active = tab === t.id;
            return (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={`flex items-center gap-1.5 text-sm px-3.5 py-2.5 border-b-2 -mb-px transition-colors ${
                  active ? 'border-ledger-blue text-ink' : 'border-transparent text-muted hover:text-ink'
                }`}
              >
                <Icon size={14} /> {t.label}
              </button>
            );
          })}
        </nav>

        <div className="flex-1 overflow-y-auto px-6 py-6">
          {!catalog && (
            <p className="text-sm text-muted">
              Drop a CSV or Excel file in the sidebar to get started.
            </p>
          )}
          {catalog && tab === 'dashboard' && <Dashboard datasetId={datasetId} catalog={catalog} selectedTable={selectedTable} onSelectTable={setSelectedTable} />}
          {catalog && tab === 'ask' && <AskPanel datasetId={datasetId} catalog={catalog} selectedTable={selectedTable} onSelectTable={setSelectedTable} />}
          {catalog && tab === 'forecast' && <ForecastPanel datasetId={datasetId} catalog={catalog} selectedTable={selectedTable} onSelectTable={setSelectedTable} />}
          {catalog && tab === 'churn' && <ChurnPanel datasetId={datasetId} catalog={catalog} selectedTable={selectedTable} onSelectTable={setSelectedTable} />}
        </div>
      </main>
    </div>
  );
}