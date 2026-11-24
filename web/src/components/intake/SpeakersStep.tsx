import { useEffect, useState } from 'react';
import { ActionGroup, Badge, Button, Content, Flex, Heading, IllustratedMessage, InlineAlert, Item, Picker, TabList, TabPanels, Tabs, Text, ToastQueue } from '@adobe/react-spectrum';
import CheckmarkCircle from '@spectrum-icons/workflow/CheckmarkCircle';
import MagicWand from '@spectrum-icons/workflow/MagicWand';
import UserGroup from '@spectrum-icons/workflow/UserGroup';
import * as api from '../../api';
import { sideLabel } from '../../bid';
import type { BidFlow } from '../../bidFlow';
import { useAsync } from '../../hooks';
import {
  callsOf, changedSides, draftOf, isExtracted, isPlaced, openSpeakers, speakersBody, speakersUnread, withSuggestions, type SpeakerDraft,
} from '../../intake';
import type { Bid, BidDocument, BidSpeaker, SpeakerSide, Status } from '../../types';
import { ErrorBox, Loading } from '../common';
import './intake.css';

const COLORS = ['blue', 'seafoam', 'orange', 'magenta', 'indigo', 'chartreuse', 'purple', 'red'];
const color = (i: number) => `var(--spectrum-global-color-${COLORS[i % COLORS.length]}-500)`;

/** Why a side was suggested, in words: "Buyer, named in the buyer's facts", "Our side, on your team list" or "No suggestion". */
function hint(s: BidSpeaker): string {
  if (!isPlaced(s.proposed)) return 'No suggestion';
  const why = s.why.replace(/^model:\s*/, '');
  const text = why === 'team list' ? 'on your team list' : why === 'B fact' ? "named in the buyer's facts" : why === 'none' ? '' : why;
  return `Suggested ${sideLabel(s.proposed)}${text ? `: ${text}` : ''}`;
}

/** Step 3: for each call, place every person on a side. What the buyer says counts above what our side says. */
export function SpeakersStep({ flow, status }: { flow: BidFlow; status: Status | null }) {
  const bid = flow.bid;
  const calls = callsOf(bid);
  if (!bid) return null;
  if (!calls.length) {
    return (
      <section className="in-card">
        <IllustratedMessage>
          <UserGroup size="XXL" />
          <Heading>No calls in this bid</Heading>
          <Content>Speakers only matter for call transcripts. Go on to review.</Content>
        </IllustratedMessage>
      </section>
    );
  }
  const hasKey = !!status?.has_key;
  const call = (d: BidDocument) => <Call key={d.no} flow={flow} bid={bid} doc={d} hasKey={hasKey} />;
  return (
    <section className="in-card" aria-labelledby="sp-h">
      <h2 id="sp-h">Call speakers</h2>
      <p className="in-lede">
        Place each person on a side: what the buyer says counts above what your team says, and what an outside adviser says depends on whom they act for.
      </p>
      {calls.length === 1 ? call(calls[0]) : (
        <Tabs aria-label="Calls">
          <TabList>{calls.map((c) => <Item key={c.no}>{`${c.file_name}${c.speakers_confirmed ? ' ✓' : ''}`}</Item>)}</TabList>
          <TabPanels>{calls.map((c) => <Item key={c.no}><div style={{ paddingTop: 16 }}>{call(c)}</div></Item>)}</TabPanels>
        </Tabs>
      )}
    </section>
  );
}

/** What the draft of a call is built from; the draft starts again when it changes. */
const signature = (d: BidDocument) => JSON.stringify([d.speakers_confirmed, d.speakers.map((s) => [s.id, s.side, s.proposed, s.why, s.acts_for])]);

function Call({ flow, bid, doc, hasKey }: { flow: BidFlow; bid: Bid; doc: BidDocument; hasKey: boolean }) {
  const [draft, setDraft] = useState<SpeakerDraft>(() => draftOf(doc.speakers));
  // A new answer from the server (a suggestion, a confirmation) starts the draft again from it.
  const sig = signature(doc);
  useEffect(() => setDraft(draftOf(doc.speakers)), [sig]); // eslint-disable-line react-hooks/exhaustive-deps
  const [hover, setHover] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const lines = useAsync(
    (signal) => api.getBidDocumentLines(bid.bid_id, doc.no, 400, signal),
    [bid.bid_id, doc.no, doc.speakers.map((s) => s.name).join('|')],
    !speakersUnread(doc),
  );
  const team = new Set(bid.team.map((t) => t.name.toLowerCase()));
  const locked = isExtracted(doc) || doc.speakers_confirmed;
  const run = async (fn: () => Promise<boolean>) => {
    setBusy(true);
    await fn();
    setBusy(false);
  };

  if (speakersUnread(doc)) {
    return (
      <InlineAlert variant="notice">
        <Heading>Speakers not read yet</Heading>
        <Content>
          {hasKey
            ? 'The model has not found who speaks each line of this call. Ask it now.'
            : 'Finding who speaks needs an API key. Without it this call cannot be read; add a key and ask again.'}
          {hasKey && (
            <div style={{ marginTop: 8 }}>
              <Button variant="primary" isDisabled={busy} onPress={() => void run(() => flow.suggestSpeakers(doc.no))}>Find speakers</Button>
            </div>
          )}
        </Content>
      </InlineAlert>
    );
  }
  if (!doc.speakers.length) {
    return (
      <InlineAlert variant="notice">
        <Heading>No speakers found</Heading>
        <Content>No one was found speaking in {doc.file_name}, so all of it counts as unclear. Confirm to go on.
          <div style={{ marginTop: 8 }}>
            {!locked && <Button variant="accent" isDisabled={busy} onPress={() => void run(() => flow.patchDocument(doc.no, { speakers_confirmed: true }))}>Confirm speakers</Button>}
          </div>
        </Content>
      </InlineAlert>
    );
  }

  const index = new Map(doc.speakers.map((p, i) => [p.name, i]));
  const open = openSpeakers(doc.speakers, draft);
  const differs = changedSides(doc.speakers, draft);
  const all = lines.data;
  const complete = !!all && all.lines.length === all.total;
  const countOf = (name: string) => (complete ? all.lines.filter((l) => l.speaker === name).length : null);
  const set = (id: string, patch: Partial<{ side: SpeakerSide; acts_for: string }>) => setDraft((d) => ({ ...d, [id]: { ...d[id], ...patch } }));
  const canSuggest = openSpeakers(doc.speakers, withSuggestions(doc.speakers, draft)).length < open.length;

  const confirm = () => run(async () => {
    const ok = await flow.patchDocument(doc.no, { speakers: speakersBody(doc.speakers, draft), speakers_confirmed: true });
    if (ok) ToastQueue.positive('Speakers confirmed', { timeout: 2500 });
    return ok;
  });

  return (
    <>
      <div className="in-call">
        <div>
          <Flex alignItems="center" gap="size-100" marginBottom="size-100">
            <strong>Transcript</strong>
            <span className="in-muted in-small">{doc.file_name}{doc.issue_date ? ` · ${doc.issue_date}` : ''}</span>
          </Flex>
          {lines.loading && !all && <Loading label="Loading the call" />}
          {lines.error && <ErrorBox message={lines.error} onRetry={lines.reload} />}
          {all && (
            <>
              <div className="in-transcript" role="list" aria-label="Transcript lines">
                {all.lines.map((l) => {
                  const at = index.get(l.speaker);
                  return (
                    <div role="listitem" key={l.id} className={`in-tline${l.speaker ? '' : ' none'}${hover && hover === l.speaker ? ' hi' : ''}`}>
                      <span className="in-stripe" style={{ background: at === undefined ? 'transparent' : color(at) }} />
                      <div>
                        {l.speaker && <div className="in-who" style={{ color: at === undefined ? undefined : color(at) }}>{l.speaker}</div>}
                        <div className="in-text">{l.text}</div>
                        {!l.speaker && <div className="in-small">No one speaks this line</div>}
                      </div>
                    </div>
                  );
                })}
              </div>
              {all.total > all.lines.length && <div className="in-muted in-small" style={{ marginTop: 6 }}>Showing the first {all.lines.length} of {all.total} lines.</div>}
            </>
          )}
        </div>
        <div>
          <Flex alignItems="center" gap="size-100" marginBottom="size-100">
            <strong>People on the call</strong>
            <span className="in-muted in-small">{doc.speakers.length}</span>
            <div style={{ flex: 1 }} />
            <Button variant="secondary" isQuiet isDisabled={locked || !canSuggest} onPress={() => setDraft(withSuggestions(doc.speakers, draft))}>
              <MagicWand />
              <Text>Use all suggestions</Text>
            </Button>
          </Flex>
          <div className="in-people">
            {doc.speakers.map((p, i) => {
              const d = draft[p.id] ?? { side: '' as SpeakerSide, acts_for: '' };
              const n = countOf(p.name);
              const meta = [p.organisation, p.title, n === null ? '' : `${n} ${n === 1 ? 'line' : 'lines'}`].filter(Boolean).join(' · ');
              return (
                <div className="in-person" key={p.id} onMouseEnter={() => setHover(p.name)} onMouseLeave={() => setHover(null)}>
                  <span className="in-swatch" style={{ background: color(i) }} />
                  <div style={{ minWidth: 0 }}>
                    <div className="in-nm">
                      {p.name}
                      {team.has(p.name.toLowerCase()) && <Badge variant="info" UNSAFE_style={{ marginLeft: 8, transform: 'scale(.85)', transformOrigin: 'left' }}>Team</Badge>}
                    </div>
                    {meta && <div className="in-muted in-small">{meta}</div>}
                    <div className="in-why"><MagicWand size="XS" /><span>{hint(p)}</span></div>
                    {d.side === 'other' && (
                      <Picker label="Acts for" labelPosition="side" isQuiet isDisabled={locked} selectedKey={d.acts_for || 'none'} width="size-3400" marginTop="size-50"
                        onSelectionChange={(k) => set(p.id, { acts_for: k === 'none' ? '' : String(k) })}>
                        <Item key="none">Neither side</Item>
                        <Item key="buyer">The buyer</Item>
                        <Item key="ours">Our side</Item>
                      </Picker>
                    )}
                  </div>
                  {locked ? (
                    <Badge variant={isPlaced(d.side) ? 'neutral' : 'yellow'}>{isPlaced(d.side) ? sideLabel(d.side) : 'No side'}</Badge>
                  ) : (
                  <ActionGroup
                    aria-label={`Side of ${p.name}`}
                    selectionMode="single"
                    selectedKeys={isPlaced(d.side) ? [d.side] : []}
                    onSelectionChange={(k) => { const v = [...k][0]; if (v) set(p.id, { side: v as SpeakerSide }); }}
                    density="compact"
                    isEmphasized
                  >
                    <Item key="buyer">Buyer</Item>
                    <Item key="ours">Our side</Item>
                    <Item key="other">Other</Item>
                  </ActionGroup>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>
      <div className="in-confirm-bar">
        {doc.speakers_confirmed ? (
          <Flex alignItems="center" gap="size-100"><CheckmarkCircle color="positive" /><span>Speakers confirmed</span></Flex>
        ) : (
          <span className="in-muted in-small">
            {open.length
              ? `${open.length} ${open.length === 1 ? 'person has' : 'people have'} no side yet.`
              : differs ? `You changed ${differs} suggested ${differs === 1 ? 'side' : 'sides'}.` : 'All sides are set.'}
          </span>
        )}
        <div className="in-grow" />
        {hasKey && !locked && (
          <Button variant="secondary" style="outline" isQuiet isDisabled={busy} onPress={() => void run(() => flow.suggestSpeakers(doc.no))}>Suggest again</Button>
        )}
        {doc.speakers_confirmed && !isExtracted(doc) && (
          <Button variant="secondary" isDisabled={busy} onPress={() => void run(() => flow.patchDocument(doc.no, { speakers_confirmed: false }))}>Change speakers</Button>
        )}
        {!locked && <Button variant="accent" isDisabled={open.length > 0 || busy} onPress={() => void confirm()}>Confirm speakers</Button>}
      </div>
    </>
  );
}
