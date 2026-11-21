import { useState } from 'react';
import { Badge, Button, RadioGroup, Radio, TextField } from '@adobe/react-spectrum';
import * as api from '../api';
import { useRun } from '../store';
import type { Conflict } from '../types';
import { FactLink, formatTime } from './common';

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

  return (
    <section className="card" aria-label={`Conflict: ${conflict.title}`}>
      <div className="row">
        <h3 className="wrap-text" style={{ flex: 1, fontSize: 16 }}>{conflict.title}</h3>
        <Badge variant={resolved ? 'positive' : 'yellow'}>{resolved ? 'Resolved' : 'Needs your choice'}</Badge>
      </div>
      {conflict.description && <div className="wrap-text">{conflict.description}</div>}
      {conflict.fact_ids.length > 0 && (
        <div className="row muted">
          Facts: {conflict.fact_ids.map((id) => <FactLink key={id} id={id} label={id} />)}
        </div>
      )}
      {resolved ? (
        <>
          <div>
            <strong>Your choice: </strong>
            <span className="wrap-text">
              {conflict.resolution?.option === null ? 'Your own answer: ' : ''}
              {conflict.resolution?.label ? `${conflict.resolution.label}. ` : ''}
              {conflict.resolution?.text}
            </span>
            {conflict.resolution?.at && <div className="muted">{formatTime(conflict.resolution.at)}</div>}
          </div>
          <div>
            <Button variant="secondary" isDisabled={busy} onPress={reopen}>
              Reopen
            </Button>
          </div>
        </>
      ) : (
        <>
          <RadioGroup
            label="Options"
            value={choice}
            onChange={(v) => {
              setChoice(v);
              setCustom('');
            }}
          >
            {conflict.options.map((o, i) => (
              <Radio key={i} value={String(i)}>
                <div>
                  <strong className="wrap-text">{o.label}</strong>
                  {o.citation && <span className="muted"> (page {o.citation.page_label || o.citation.page})</span>}
                  {o.text && <div className="wrap-text">{o.text}</div>}
                  {o.changes.length > 0 && (
                    <ul className="muted" style={{ margin: '2px 0', paddingLeft: 18 }}>
                      {o.changes.map((c, j) => <li key={j} className="wrap-text">{describeChange(c)}</li>)}
                    </ul>
                  )}
                </div>
              </Radio>
            ))}
          </RadioGroup>
          <TextField
            label="Or write your own answer"
            value={custom}
            onChange={(v) => {
              setCustom(v);
              if (v) setChoice('');
            }}
            width="100%"
          />
          <div>
            <Button variant="accent" isDisabled={!canSubmit} onPress={submit}>
              Use this choice
            </Button>
          </div>
        </>
      )}
    </section>
  );
}
