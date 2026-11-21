import { useState } from 'react';
import { Button } from '@adobe/react-spectrum';
import * as api from '../api';
import { useRun } from '../store';
import type { Conflict } from '../types';
import { FactLink, formatTime } from './common';
import './pages.css';

function describeChange(c: { op: string; fact_id: string; fields?: Record<string, unknown> }): string {
  if (c.op === 'delete') return `Delete fact ${c.fact_id}`;
  const parts = Object.entries(c.fields ?? {}).map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : String(v)}`);
  return `Change fact ${c.fact_id}${parts.length ? ` (${parts.join('; ')})` : ''}`;
}

export function ConflictCard({ conflict }: { conflict: Conflict }) {
  const { run, act } = useRun();
  const [choice, setChoice] = useState<string>('');
  const [custom, setCustom] = useState('');
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
        <span className={`pg-pill ${resolved ? 'ok' : 'warn'}`}>{resolved ? 'Resolved' : 'Needs your choice'}</span>
      </div>
      {conflict.description && <div className="cf-desc">{conflict.description}</div>}
      {conflict.fact_ids.length > 0 && (
        <div className="cf-facts">
          Facts: {conflict.fact_ids.map((id) => <FactLink key={id} id={id} label={id} />)}
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
            {conflict.options.map((o, i) => (
              <label key={i} className={`cf-opt${choice === String(i) ? ' sel' : ''}`}>
                <input
                  type="radio"
                  name={groupName}
                  value={String(i)}
                  checked={choice === String(i)}
                  onChange={() => {
                    setChoice(String(i));
                    setCustom('');
                  }}
                />
                <span className="cf-opt-body">
                  <span className="cf-opt-top">
                    <span className="cf-opt-label">{o.label}</span>
                    {o.citation && <span className="cf-page">page {o.citation.page_label || o.citation.page}</span>}
                  </span>
                  {o.text && <blockquote className="cf-quote">{o.text}</blockquote>}
                  {o.changes.length > 0 && (
                    <ul className="cf-changes">
                      {o.changes.map((c, j) => <li key={j} className="wrap-text">{describeChange(c)}</li>)}
                    </ul>
                  )}
                </span>
              </label>
            ))}
          </fieldset>
          <label className="cf-own">
            Or write your own answer
            <input
              type="text"
              value={custom}
              onChange={(e) => {
                setCustom(e.target.value);
                if (e.target.value) setChoice('');
              }}
            />
          </label>
          <div className="cf-foot">
            <Button variant="accent" isDisabled={!canSubmit} onPress={submit}>
              Use this choice
            </Button>
          </div>
        </>
      )}
    </section>
  );
}
