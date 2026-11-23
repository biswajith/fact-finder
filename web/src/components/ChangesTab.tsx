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
  reject_relation: 'Link rejected',
  ungroup: 'Ungrouped',
};

/** The changes still in effect: not undone, and not the undo entries themselves. The sidebar pill and this page's header both count these. */
export const activeChanges = (list: CorrectionEntry[]) => list.filter((c) => !c.undone && c.op !== 'undo');

const fmt = (v: unknown) =>
  Array.isArray(v) ? v.join(', ') || '(none)' : v === '' ? '(empty)' : v !== null && typeof v === 'object' ? JSON.stringify(v) : String(v);

export function ChangesTab() {
  const { run, corrections, reloadAll, act } = useRun();
  if (corrections.loading && !corrections.data) return <Loading label="Loading changes" />;
  if (corrections.error && !corrections.data) return <ErrorBox message={corrections.error} onRetry={() => void reloadAll()} />;
  const list = corrections.data ?? [];
  const active = activeChanges(list).length;
  const undoneCount = list.filter((c) => c.undone).length;
  return (
    <>
      <PageHeader title="Changes" subtitle={list.length ? `${active} change${active === 1 ? '' : 's'}${undoneCount ? ` · ${undoneCount} undone` : ''}` : undefined} />
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
            // A raise names its conflict above; a choice shows the chosen option instead of its index.
            const fields = c.op === 'raise' || c.op === 'resolve' || c.op === 'reject_relation' || c.op === 'ungroup' ? {} : c.fields ?? {};
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
                    <FactLink id={c.fact_id} />
                    {c.fact_text && <span className="wrap-text muted">{c.fact_text}</span>}
                  </div>
                )}
                {c.description && <div className="wrap-text">{c.description}</div>}
                {c.conflict_id && !c.fact_id && (
                  <div className="wrap-text">Conflict: {c.conflict_title ?? <span className="muted">no longer listed</span>}</div>
                )}
                {c.op === 'resolve' && c.choice && (
                  <div className="tl-diff">
                    <span className="k">Chosen</span>
                    <span className="new">{c.choice}</span>
                  </div>
                )}
                {Object.entries(fields).map(([k, v]) => {
                  const before = c.op === 'edit' ? c.before?.[k] : undefined;
                  return (
                    <div key={k} className="tl-diff">
                      <span className="k">{(k[0].toUpperCase() + k.slice(1)).replace(/_/g, ' ')}</span>
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
