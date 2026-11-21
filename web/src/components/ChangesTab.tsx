import { Badge, Button } from '@adobe/react-spectrum';
import * as api from '../api';
import { useRun } from '../store';
import type { CorrectionEntry } from '../types';
import { Empty, ErrorBox, FactLink, Loading, formatTime } from './common';

const OP_LABEL: Record<CorrectionEntry['op'], string> = {
  edit: 'Changed',
  delete: 'Deleted',
  add: 'Added',
  raise: 'Conflict found',
  resolve: 'Choice made',
  undo: 'Undo',
};

const fmt = (v: unknown) =>
  Array.isArray(v) ? v.join(', ') || '(none)' : v === '' ? '(empty)' : v !== null && typeof v === 'object' ? JSON.stringify(v) : String(v);

export function ChangesTab() {
  const { run, corrections, factById, reloadAll, act } = useRun();
  if (corrections.loading && !corrections.data) return <Loading label="Loading changes" />;
  if (corrections.error && !corrections.data) return <ErrorBox message={corrections.error} onRetry={() => void reloadAll()} />;
  const list = corrections.data ?? [];
  return (
    <div className="panel">
      {corrections.error && <ErrorBox message={corrections.error} onRetry={() => void reloadAll()} />}
      {list.length === 0 && <Empty>Nothing has been changed yet.</Empty>}
      {list.map((c) => {
        const fact = c.fact_id ? factById.get(c.fact_id) : undefined;
        return (
          <section key={c.id} className="card" aria-label={`${OP_LABEL[c.op]} ${c.fact_id ?? c.conflict_id ?? ''}`}>
            <div className="row">
              <Badge variant={c.undone ? 'neutral' : 'info'}>{OP_LABEL[c.op]}</Badge>
              <span className="muted">
                {formatTime(c.at)} · from {c.source === 'chat' ? 'chat' : 'the screen'}
              </span>
              {c.undone && <Badge variant="neutral">Undone</Badge>}
              <span style={{ flex: 1 }} />
              {!c.undone && c.op !== 'undo' && (
                <Button variant="secondary" aria-label={`Undo change ${c.id}`} onPress={() => void act(() => api.undoCorrection(run, c.id), 'Change undone')}>
                  Undo
                </Button>
              )}
            </div>
            {c.fact_id && (
              <div className="row">
                <FactLink id={c.fact_id} label={c.fact_id} />
                {c.fact_text && <span className="wrap-text muted">{c.fact_text}</span>}
              </div>
            )}
            {c.conflict_id && !c.fact_id && <div className="muted">Conflict {c.conflict_id}</div>}
            {c.target && <div className="muted">Cancels change {c.target}</div>}
            {c.fields &&
              Object.entries(c.op === 'raise' ? { title: c.fields.title } : c.fields).map(([k, v]) => {
                const before = c.op === 'edit' && fact?.original ? (fact.original as Record<string, unknown>)[k] : undefined;
                return (
                  <div key={k} className="wrap-text">
                    <strong>{k === 'option' ? 'Option' : k[0].toUpperCase() + k.slice(1)}: </strong>
                    {before !== undefined && <span className="old">{fmt(before)}</span>}
                    {before !== undefined && ' → '}
                    {fmt(v)}
                  </div>
                );
              })}
            {c.reason && <div className="muted wrap-text">Reason: {c.reason}</div>}
          </section>
        );
      })}
    </div>
  );
}
