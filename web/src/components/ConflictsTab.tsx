import { useRun } from '../store';
import { ConflictCard } from './ConflictCard';
import { Empty, ErrorBox, Loading } from './common';

export function ConflictsTab() {
  const { conflicts, reloadAll } = useRun();
  if (conflicts.loading && !conflicts.data) return <Loading label="Loading conflicts" />;
  if (conflicts.error && !conflicts.data) return <ErrorBox message={conflicts.error} onRetry={() => void reloadAll()} />;
  const list = [...(conflicts.data ?? [])].sort((a, b) => Number(a.status === 'resolved') - Number(b.status === 'resolved'));
  return (
    <div className="panel">
      {conflicts.error && <ErrorBox message={conflicts.error} onRetry={() => void reloadAll()} />}
      {list.length === 0 ? <Empty>No conflicts. Nothing in this run needs your choice.</Empty> : list.map((c) => <ConflictCard key={c.id} conflict={c} />)}
    </div>
  );
}
