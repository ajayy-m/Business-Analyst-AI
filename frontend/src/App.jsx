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

  const refreshCatalog = useCallback(() => {
    if (!datasetId) return;
    getCatalog(datasetId)
      .then(setCatalog)
      .catch(() => setCatalog(null));
  }, [datasetId]);

  useEffect(() => {
    refreshCatalog();
  }, [refreshCatalog]);

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar datasetId={datasetId} onUploaded={refreshCatalog} catalog={catalog} />

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
          {catalog && tab === 'dashboard' && <Dashboard datasetId={datasetId} catalog={catalog} />}
          {catalog && tab === 'ask' && <AskPanel datasetId={datasetId} />}
          {catalog && tab === 'forecast' && <ForecastPanel datasetId={datasetId} catalog={catalog} />}
          {catalog && tab === 'churn' && <ChurnPanel datasetId={datasetId} catalog={catalog} />}
        </div>
      </main>
    </div>
  );
}