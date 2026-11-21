import { Button } from '@adobe/react-spectrum';
import * as api from '../api';
import { useRun } from '../store';
import type { CorrectionEntry } from '../types';
import { ErrorBox, FactLink, Loading, formatTime } from './common';
import { PageHeader } from './shell/PageHeader';
import './pages.css';

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
  const undoneCount = list.filter((c) => c.undone).length;
  return (
    <>
      <PageHeader title="Changes" subtitle={list.length ? `${list.length} change${list.length === 1 ? '' : 's'}${undoneCount ? ` · ${undoneCount} undone` : ''}` : undefined} />
      <div className="pg-stack">
        {corrections.error && <ErrorBox message={corrections.error} onRetry={() => void reloadAll()} />}
        {list.length === 0 && (
          <div className="pg-empty">
            <strong>No changes yet</strong>
            <span>Nothing has been changed yet.</span>
          </div>
        )}
        <ol className="tl">
          {list.map((c) => {
            const fact = c.fact_id ? factById.get(c.fact_id) : undefined;
            return (
              <li key={c.id} className={`tl-item${c.undone ? ' undone' : ''}`} aria-label={`${OP_LABEL[c.op]} ${c.fact_id ?? c.conflict_id ?? ''}`}>
                <div className="tl-head">
                  <span className={`pg-pill ${c.undone ? '' : 'info'}`}>{OP_LABEL[c.op]}</span>
                  {c.undone && <span className="pg-pill">Undone</span>}
                  <span className="tl-when">
                    {formatTime(c.at)} · from {c.source === 'chat' ? 'chat' : 'the screen'}
                  </span>
                  <span className="tl-spacer" />
                  {!c.undone && c.op !== 'undo' && (
                    <Button variant="secondary" aria-label={`Undo change ${c.id}`} onPress={() => void act(() => api.undoCorrection(run, c.id), 'Change undone')}>
                      Undo
                    </Button>
                  )}
                </div>
                {c.fact_id && (
                  <div className="tl-fact">
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
                      <div key={k} className="tl-diff">
                        <span className="k">{k === 'option' ? 'Option' : k[0].toUpperCase() + k.slice(1)}</span>
                        <span>
                          {before !== undefined && <span className="old">{fmt(before)}</span>}
                          {before !== undefined && <span className="arrow">→</span>}
                          <span className="new">{fmt(v)}</span>
                        </span>
                      </div>
                    );
                  })}
                {c.reason && <div className="tl-reason">Reason: {c.reason}</div>}
              </li>
            );
          })}
        </ol>
      </div>
    </>
  );
}
