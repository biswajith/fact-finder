import { useState } from 'react';
import { Button } from '@adobe/react-spectrum';
import * as api from '../api';
import { levelChip, optionEffects, reasonWords, useBidDocs } from '../bidDocs';
import { useRun } from '../store';
import type { Conflict } from '../types';
import { FactLink, formatTime } from './common';
import './facts.css';
import './pages.css';

function describeChange(c: { op: string; fact_id: string; fields?: Record<string, unknown> }): string {
  if (c.op === 'delete') return `Delete fact ${c.fact_id}`;
  const parts = Object.entries(c.fields ?? {}).map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : String(v)}`);
  return `Change fact ${c.fact_id}${parts.length ? ` (${parts.join('; ')})` : ''}`;
}

const clip = (s: string, n = 60) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);

/** The facts a document conflict is about: each with its document and level, and "tentative" when it is. */
function DocFacts({ ids }: { ids: string[] }) {
  const { factById } = useRun();
  const docs = useBidDocs();
  return (
    <ul className="cf-docfacts">
      {ids.map((id) => {
        const f = factById.get(id);
        const d = f?.doc_no ? docs.byNo.get(f.doc_no) : f?.doc_id ? docs.byId.get(f.doc_id) : undefined;
        return (
          <li key={id}>
            <div className="cf-docfact-top">
              {d && <span className="pg-pill">{`d${d.no} ${d.file_name}`}</span>}
              {f?.level ? <span className="pg-pill info">{levelChip(f.level)}</span> : null}
              {f?.flags.includes('tentative') && <span className="pg-pill warn">tentative</span>}
            </div>
            <div className="wrap-text">{f ? f.text : <FactLink id={id} />}</div>
            {f && <FactLink id={id} label="Open this fact" />}
          </li>
        );
      })}
    </ul>
  );
}

export function ConflictCard({ conflict }: { conflict: Conflict }) {
  const { run, act, factById } = useRun();
  const docs = useBidDocs();
  const isDoc = conflict.kind === 'document';
  const settledBy = isDoc && conflict.closed_by ? docs.byId.get(conflict.closed_by) : undefined;
  const ref = (id: string) => {
    const f = factById.get(id);
    return f ? `${f.doc_no ? `d${f.doc_no} ` : ''}fact "${clip(f.text, 50)}"` : `fact ${id}`;
  };
  const [choice, setChoice] = useState<string>('');
  const [custom, setCustom] = useState('');
  const [own, setOwn] = useState(false);
  const [busy, setBusy] = useState(false);
  const resolved = conflict.status === 'resolved';
  const canSubmit = !busy && (custom.trim() !== '' || choice !== '');

  const submit = async () => {
    setBusy(true);
    const body = custom.trim() ? { text: custom.trim() } : { option: Number(choice) };
    await act(() => api.resolveConflict(run, conflict.id, body), 'Choice saved');
    setBusy(false);
  };
  const reopen = async () => {
    setBusy(true);
    await act(() => api.reopenConflict(run, conflict.id), 'Conflict reopened');
    setBusy(false);
  };

  const groupName = `conflict-${conflict.id}`;
  return (
    <section className={`cf-card ${resolved ? 'resolved' : 'open'}`} aria-label={`Conflict: ${conflict.title}`}>
      <div className="cf-head">
        <h3 className="cf-title">{conflict.title}</h3>
        {isDoc && conflict.closed_by && <span className="pg-pill ok">Settled by {settledBy ? `d${settledBy.no} ${settledBy.file_name}` : conflict.closed_by}</span>}
        <span className={`pg-pill ${resolved ? 'ok' : 'warn'}`}>{resolved ? 'Resolved' : 'Needs your choice'}</span>
      </div>
      {isDoc && reasonWords(conflict.reason) && <div className="cf-reason">{reasonWords(conflict.reason)}</div>}
      {conflict.kind !== 'source' && conflict.description && <div className="cf-desc">{conflict.description}</div>}
      {isDoc && conflict.fact_ids.length > 0 ? (
        <DocFacts ids={conflict.fact_ids} />
      ) : conflict.fact_ids.length > 0 && (
        <div className="cf-facts">
          Facts: {conflict.fact_ids.map((id) => <FactLink key={id} id={id} />)}
        </div>
      )}
      {resolved ? (
        <>
          <div className="cf-resolution">
            <span className="k">Your choice</span>
            <span className="wrap-text">
              {conflict.resolution?.option === null ? 'Your own answer: ' : ''}
              {conflict.resolution?.label ? `${conflict.resolution.label}. ` : ''}
              {conflict.resolution?.text}
            </span>
            {conflict.resolution?.at && <span className="muted">{formatTime(conflict.resolution.at)}</span>}
          </div>
          <div className="cf-foot">
            <Button variant="secondary" isDisabled={busy} onPress={reopen}>
              Reopen
            </Button>
          </div>
        </>
      ) : (
        <>
          <fieldset className="cf-options" role="radiogroup">
            <legend>Options</legend>
            {(isDoc ? [...conflict.options.keys()].sort((a, b) => Number(!!conflict.options[a].question) - Number(!!conflict.options[b].question)) : [...conflict.options.keys()]).map((i) => {
              const o = conflict.options[i];
              return (
              <label key={i} className={`cf-opt${choice === String(i) ? ' sel' : ''}${isDoc && o.question ? ' ask' : ''}`}>
                <input
                  type="radio"
                  name={groupName}
                  value={String(i)}
                  checked={choice === String(i)}
                  onChange={() => {
                    setChoice(String(i));
                    setCustom('');
                    setOwn(false);
                  }}
                />
                <span className="cf-opt-body">
                  <span className="cf-opt-top">
                    <span className="cf-opt-label">{o.label}</span>
                    {conflict.kind === 'raised' && o.citation && <span className="cf-page">page {o.citation.page_label || o.citation.page}</span>}
                  </span>
                  {o.text && <blockquote className="cf-quote">{o.text}</blockquote>}
                  {isDoc ? (
                    <ul className="cf-changes">
                      {optionEffects(o, ref).map((t, j) => <li key={j} className="wrap-text">{t}</li>)}
                    </ul>
                  ) : o.changes.length > 0 && (
                    <ul className="cf-changes">
                      {o.changes.map((c, j) => <li key={j} className="wrap-text">{describeChange(c)}</li>)}
                    </ul>
                  )}
                </span>
              </label>
              );
            })}
          </fieldset>
          {own && (
            <label className="cf-own">
              Your own answer
              <input
                type="text"
                autoFocus
                value={custom}
                onChange={(e) => {
                  setCustom(e.target.value);
                  if (e.target.value) setChoice('');
                }}
              />
            </label>
          )}
          <div className="cf-foot">
            {!own && (
              <button type="button" className="linkbtn cf-own-toggle" onClick={() => setOwn(true)}>
                Write your own answer
              </button>
            )}
            <Button variant="accent" isDisabled={!canSubmit} onPress={submit}>
              Use this choice
            </Button>
          </div>
        </>
      )}
    </section>
  );
}
