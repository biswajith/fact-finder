import { useState } from 'react';
import { Button, Radio, RadioGroup, TextField } from '@adobe/react-spectrum';
import { sideLabel } from '../../bid';
import type { BidDocument, BidSpeaker, SpeakerSide } from '../../types';

/** A phone number or "Speaker 2": a name the reader may need to type. */
const anonymous = (name: string) => name.startsWith('+') || name.startsWith('Speaker ');
const placed = (x: SpeakerSide | undefined) => x === 'buyer' || x === 'ours' || x === 'other';
const NOT_IDENTIFIED = 'Not identified';

/** "suggested: Buyer — works for the city", "suggested: Our side — team list" or "no suggestion". */
function hint(s: BidSpeaker): string {
  if (!placed(s.proposed)) return 'no suggestion';
  const why = s.why.replace(/^model:\s*/, '');
  return `suggested: ${sideLabel(s.proposed)}${why && why !== 'none' ? ` — ${why}` : ''}`;
}

/** The speakers by organisation, in order of first appearance and those with none last; a single group (no heading) unless two share one. */
function groups(speakers: BidSpeaker[]): { name: string | null; at: number[] }[] {
  const count = new Map<string, number>();
  for (const s of speakers) if (s.organisation) count.set(s.organisation, (count.get(s.organisation) ?? 0) + 1);
  if (![...count.values()].some((n) => n >= 2)) return [{ name: null, at: speakers.map((_, i) => i) }];
  const by = new Map<string, number[]>();
  speakers.forEach((s, i) => by.set(s.organisation || NOT_IDENTIFIED, [...(by.get(s.organisation || NOT_IDENTIFIED) ?? []), i]));
  const named = [...by].filter(([k]) => k !== NOT_IDENTIFIED).map(([name, at]) => ({ name, at }));
  return by.has(NOT_IDENTIFIED) ? [...named, { name: NOT_IDENTIFIED, at: by.get(NOT_IDENTIFIED) as number[] }] : named;
}

export function SpeakersPanel({ doc, onConfirm, onSuggest }: {
  doc: BidDocument;
  onConfirm: (speakers: { id: string; name: string; side: SpeakerSide }[]) => Promise<boolean>;
  /** Ask the model again; absent when there is no API key. */
  onSuggest?: () => Promise<boolean>;
}) {
  const [open, setOpen] = useState(!doc.speakers_confirmed);
  // A side the reader has not chosen starts from the proposal when there is one; "unknown" stays unselected.
  const [draft, setDraft] = useState(() => doc.speakers.map((s) => ({ id: s.id, name: s.name, side: placed(s.side) ? s.side : placed(s.proposed) ? s.proposed : s.side })));
  const [busy, setBusy] = useState(false);
  const locked = !!doc.run;
  const complete = draft.every((s) => placed(s.side));
  const set = (i: number, patch: Partial<{ name: string; side: SpeakerSide }>) =>
    setDraft((d) => d.map((s, j) => (j === i ? { ...s, ...patch } : s)));

  const line = (i: number) => {
    const s = draft[i];
    const orig = doc.speakers[i];
    const who = [orig.organisation, orig.title].filter(Boolean).join(' · ');
    return (
      <div className="pg-speaker" key={s.id}>
        <div className="pg-speaker-name">
          {anonymous(orig.name) && !locked ? (
            <TextField aria-label={`Name of ${orig.name}`} value={s.name} onChange={(v) => set(i, { name: v })} />
          ) : (
            <strong>{s.name}</strong>
          )}
          <span className="muted">{who ? `${who} · ` : ''}{hint(orig)}</span>
        </div>
        <RadioGroup
          aria-label={`Side of ${s.name}`}
          orientation="horizontal"
          value={placed(s.side) ? s.side : ''}
          isDisabled={locked}
          onChange={(v) => set(i, { side: v as SpeakerSide })}
        >
          <Radio value="buyer">Buyer</Radio>
          <Radio value="ours">Our side</Radio>
          <Radio value="other">Other party</Radio>
        </RadioGroup>
        {s.side === 'other' && (orig.acts_for === 'buyer' || orig.acts_for === 'ours') && (
          <span className="muted">acts for {orig.acts_for === 'buyer' ? 'the buyer' : 'our side'}</span>
        )}
      </div>
    );
  };

  return (
    <details className="pg-fold pg-speakers" open={open} onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary>Speakers of d{doc.no}{doc.speakers_confirmed ? ' (confirmed)' : ''}</summary>
      <div className="pg-speaker-list">
        {groups(doc.speakers).map((g) => (
          <div key={g.name ?? ''} className="pg-speaker-group">
            {g.name && <div className="pg-speaker-org muted"><strong>{g.name}</strong></div>}
            {g.at.map(line)}
          </div>
        ))}
      </div>
      {!locked && (
        <div className="row">
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
          {onSuggest && !doc.speakers_confirmed && (
            <Button
              variant="secondary"
              style="outline"
              isQuiet
              isDisabled={busy}
              onPress={async () => {
                setBusy(true);
                await onSuggest();
                setBusy(false);
              }}
            >
              Suggest again
            </Button>
          )}
        </div>
      )}
    </details>
  );
}
