import { useRun } from '../store';
import { ConflictCard } from './ConflictCard';
import { ErrorBox, Loading } from './common';
import { PageHeader } from './shell/PageHeader';
import './pages.css';

export function ConflictsTab() {
  const { conflicts, reloadAll } = useRun();
  if (conflicts.loading && !conflicts.data) return <Loading label="Loading conflicts" />;
  if (conflicts.error && !conflicts.data) return <ErrorBox message={conflicts.error} onRetry={() => void reloadAll()} />;
  const all = conflicts.data ?? [];
  const open = all.filter((c) => c.status !== 'resolved');
  const resolved = all.filter((c) => c.status === 'resolved');
  return (
    <>
      <PageHeader title="Conflicts" subtitle={`${open.length} open · ${resolved.length} resolved`} />
      <div className="pg-stack">
        {conflicts.error && <ErrorBox message={conflicts.error} onRetry={() => void reloadAll()} />}
        {open.length === 0 && (
          <div className="pg-empty">
            <strong>{all.length === 0 ? 'No conflicts' : 'All conflicts resolved'}</strong>
            <span>{all.length === 0 ? 'Nothing in this run needs your choice.' : 'Nothing is waiting for your choice.'}</span>
          </div>
        )}
        {open.map((c) => <ConflictCard key={c.id} conflict={c} />)}
        {resolved.length > 0 && (
          <details className="cf-resolved-sec">
            <summary>Resolved ({resolved.length})</summary>
            <div className="cf-resolved-list">
              {resolved.map((c) => <ConflictCard key={c.id} conflict={c} />)}
            </div>
          </details>
        )}
      </div>
    </>
  );
}
