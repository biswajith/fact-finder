import { useState } from 'react';
import { Button, Radio, RadioGroup, TextField } from '@adobe/react-spectrum';
import type { BidDocument, SpeakerSide } from '../../types';

const SIDE_WORDS: Record<string, string> = { buyer: 'Buyer', ours: 'Our side' };
/** A phone number or "Speaker 2": a name the reader may need to type. */
const anonymous = (name: string) => name.startsWith('+') || name.startsWith('Speaker ');

export function SpeakersPanel({ doc, onConfirm }: {
  doc: BidDocument;
  onConfirm: (speakers: { id: string; name: string; side: SpeakerSide }[]) => Promise<boolean>;
}) {
  const [open, setOpen] = useState(!doc.speakers_confirmed);
  const [draft, setDraft] = useState(() => doc.speakers.map((s) => ({ id: s.id, name: s.name, side: s.side })));
  const [busy, setBusy] = useState(false);
  const locked = !!doc.run;
  const complete = draft.every((s) => s.side === 'buyer' || s.side === 'ours');
  const set = (i: number, patch: Partial<{ name: string; side: SpeakerSide }>) =>
    setDraft((d) => d.map((s, j) => (j === i ? { ...s, ...patch } : s)));

  return (
    <details className="pg-fold pg-speakers" open={open} onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary>Speakers of d{doc.no}{doc.speakers_confirmed ? ' (confirmed)' : ''}</summary>
      <div className="pg-speaker-list">
        {draft.map((s, i) => {
          const orig = doc.speakers[i];
          const hint = orig.proposed === 'buyer' || orig.proposed === 'ours' ? `suggested: ${SIDE_WORDS[orig.proposed]}, ${orig.why}` : 'no suggestion';
          return (
            <div className="pg-speaker" key={s.id}>
              <div className="pg-speaker-name">
                {anonymous(orig.name) && !locked ? (
                  <TextField aria-label={`Name of ${orig.name}`} value={s.name} onChange={(v) => set(i, { name: v })} />
                ) : (
                  <strong>{s.name}</strong>
                )}
                <span className="muted">{hint}</span>
              </div>
              <RadioGroup
                aria-label={`Side of ${s.name}`}
                orientation="horizontal"
                value={s.side === 'buyer' || s.side === 'ours' ? s.side : ''}
                isDisabled={locked}
                onChange={(v) => set(i, { side: v as SpeakerSide })}
              >
                <Radio value="buyer">Buyer</Radio>
                <Radio value="ours">Our side</Radio>
              </RadioGroup>
            </div>
          );
        })}
      </div>
      {!locked && (
        <Button
          variant="accent"
          isDisabled={!complete || busy}
          onPress={async () => {
            setBusy(true);
            const ok = await onConfirm(draft.map((s) => ({ id: s.id, name: s.name.trim() || s.name, side: s.side })));
            setBusy(false);
            if (ok) setOpen(false);
          }}
        >
          Confirm speakers
        </Button>
      )}
    </details>
  );
}
