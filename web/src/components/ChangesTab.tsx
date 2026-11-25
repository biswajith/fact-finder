import Add from '@spectrum-icons/workflow/Add';
import Branch1 from '@spectrum-icons/workflow/Branch1';
import Checkmark from '@spectrum-icons/workflow/Checkmark';
import Delete from '@spectrum-icons/workflow/Delete';
import Edit from '@spectrum-icons/workflow/Edit';
import LinkOff from '@spectrum-icons/workflow/LinkOff';
import Undo from '@spectrum-icons/workflow/Undo';
import Ungroup from '@spectrum-icons/workflow/Ungroup';
import type { ReactNode } from 'react';
import * as api from '../api';
import { fieldName, fieldValue, wordDiff } from '../changesView';
import { useRun } from '../store';
import type { CorrectionEntry, Fact } from '../types';
import { CATEGORY_NAMES } from '../types';
import { ErrorBox, FactLink, Loading, firstPage, formatTime } from './common';
import { PageHeader } from './shell/PageHeader';
import './pages.css';

const OP_LABEL: Record<CorrectionEntry['op'], string> = {
  edit: 'Fact changed',
  delete: 'Fact deleted',
  add: 'Fact added',
  raise: 'Conflict found',
  resolve: 'Choice made',
  undo: 'Undo',
  reject_relation: 'Link rejected',
  ungroup: 'Ungrouped',
  set_value: 'Value set',
};

/** The changes still in effect: not undone, and not the undo entries themselves. The sidebar pill and this page's header both count these. */
export const activeChanges = (list: CorrectionEntry[]) => list.filter((c) => !c.undone && c.op !== 'undo');

const ICON: Record<CorrectionEntry['op'], { icon: ReactNode; tone: string }> = {
  add: { icon: <Add size="S" />, tone: 'ok' },
  edit: { icon: <Edit size="S" />, tone: 'accent' },
  delete: { icon: <Delete size="S" />, tone: 'bad' },
  raise: { icon: <Branch1 size="S" />, tone: 'warn' },
  resolve: { icon: <Checkmark size="S" />, tone: 'ok' },
  undo: { icon: <Undo size="S" />, tone: 'muted' },
  reject_relation: { icon: <LinkOff size="S" />, tone: 'muted' },
  ungroup: { icon: <Ungroup size="S" />, tone: 'muted' },
  set_value: { icon: <Edit size="S" />, tone: 'accent' },
};

/** Where a fact comes from, in words: "Page 8", or a note when its citations could not be found. */
function sourceTag(f: Fact | undefined): string | null {
  if (!f) return null;
  const page = firstPage(f);
  if (page) return `Page ${page}`;
  return f.unresolved_ids?.length ? 'Source not found' : null;
}

/** What one change did, as a sentence or a marked-up text. */
function ChangeBody({ c, fact }: { c: CorrectionEntry; fact: Fact | undefined }) {
  const fields = c.fields ?? {};
  if (c.op === 'add') {
    const cat = typeof fields.category === 'string' ? CATEGORY_NAMES[fields.category as keyof typeof CATEGORY_NAMES] ?? fields.category : null;
    const src = sourceTag(fact);
    return (
      <>
        <p className="cl-quote wrap-text">{String(fields.text ?? c.fact_text ?? '')}</p>
        <div className="cl-tags">
          {cat && <span className="cl-tag">{cat}</span>}
          {src && <span className={`cl-tag${src === 'Source not found' ? ' warn' : ''}`}>{src}</span>}
          {c.fact_id && <FactLink id={c.fact_id} label="Open fact" />}
        </div>
      </>
    );
  }
  if (c.op === 'edit') {
    const before = c.before ?? {};
    return (
      <>
        {Object.entries(fields).map(([k, v]) =>
          k === 'text' && typeof v === 'string' && typeof before.text === 'string' ? (
            <p key={k} className="cl-quote wrap-text">
              {wordDiff(before.text, v).map((p, i) =>
                p.kind === 'same' ? <span key={i}>{p.text}</span> : p.kind === 'del' ? <del key={i}>{p.text}</del> : <ins key={i}>{p.text}</ins>,
              )}
            </p>
          ) : (
            <p key={k} className="cl-field wrap-text">
              <span className="muted">{fieldName(k)}: </span>
              {k in before && <><del>{fieldValue(k, before[k])}</del> → </>}
              <ins>{fieldValue(k, v)}</ins>
            </p>
          ),
        )}
        {c.fact_id && <div className="cl-tags"><FactLink id={c.fact_id} label="Open fact" /></div>}
      </>
    );
  }
  if (c.op === 'delete') {
    return (
      <>
        {c.fact_text && <p className="cl-quote wrap-text"><del>{c.fact_text}</del></p>}
        {c.fact_id && <div className="cl-tags"><FactLink id={c.fact_id} label="Open fact" /></div>}
      </>
    );
  }
  if (c.op === 'raise' || c.op === 'resolve') {
    return (
      <>
        <p className="cl-quote wrap-text">{c.conflict_title ?? <span className="muted">A conflict that is no longer listed</span>}</p>
        {c.op === 'resolve' && c.choice && <p className="cl-field wrap-text"><span className="muted">Chosen: </span><strong>{c.choice}</strong></p>}
      </>
    );
  }
  if (c.description) return <p className="cl-quote wrap-text">{c.description}</p>;
  if (c.op === 'undo') return <p className="cl-field muted">An earlier change was undone.</p>;
  return null;
}

export function ChangesTab() {
  const { run, corrections, reloadAll, act, factById } = useRun();
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
        <ol className="cl">
          {list.map((c) => {
            const { icon, tone } = ICON[c.op];
            const fact = c.fact_id ? factById.get(c.fact_id) : undefined;
            return (
              <li key={c.id} className={`cl-item${c.undone ? ' undone' : ''}`} aria-label={`${OP_LABEL[c.op]} ${c.fact_id ?? c.conflict_id ?? ''}`}>
                <span className={`cl-icon ${c.undone ? 'muted' : tone}`} aria-hidden="true">{icon}</span>
                <div className="cl-main">
                  <div className="cl-head">
                    <strong>{OP_LABEL[c.op]}</strong>
                    {c.undone && <span className="cl-tag">Undone</span>}
                    <span className="cl-when">from {c.source === 'chat' ? 'chat' : 'the screen'} · {formatTime(c.at)}</span>
                  </div>
                  <ChangeBody c={c} fact={fact} />
                  {c.reason && <div className="cl-reason wrap-text">Reason: {c.reason}</div>}
                </div>
                {!c.undone && c.op !== 'undo' && (
                  <button type="button" className="linkbtn cl-undo" aria-label={`Undo change ${c.id}`}
                    onClick={() => void act(() => api.undoCorrection(run, c.id), 'Change undone')}>
                    Undo
                  </button>
                )}
              </li>
            );
          })}
        </ol>
      </div>
    </>
  );
}
