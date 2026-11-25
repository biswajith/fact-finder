import { useState } from 'react';
import {
  ActionGroup, Badge, Button, Content, Flex, Heading, IllustratedMessage, InlineAlert, Item, Picker, Tabs, TabList, TabPanels, Text, ToastQueue,
} from '@adobe/react-spectrum';
import CheckmarkCircle from '@spectrum-icons/workflow/CheckmarkCircle';
import MagicWand from '@spectrum-icons/workflow/MagicWand';
import UserGroup from '@spectrum-icons/workflow/UserGroup';
import { SIDE_LABEL, typeInfo, type Doc, type Side } from '../data';
import { useIntake } from '../store';

const COLORS = ['blue', 'seafoam', 'orange', 'magenta', 'indigo', 'chartreuse', 'purple', 'red'];
const color = (i: number) => `var(--spectrum-global-color-${COLORS[i % COLORS.length]}-500)`;

export function SpeakersStep() {
  const { s } = useIntake();
  const calls = s.docs.filter((d) => d.confirmed && typeInfo(d.type).spoken);
  if (!calls.length) {
    return (
      <section className="card">
        <IllustratedMessage>
          <UserGroup size="XXL" />
          <Heading>No calls in this bid</Heading>
          <Content>Speakers only matter for call transcripts. Go on to review.</Content>
        </IllustratedMessage>
      </section>
    );
  }
  return (
    <section className="card" aria-labelledby="sp-h">
      <h2 id="sp-h">Call speakers</h2>
      <p className="lede">
        The model read each call and found who speaks every line. Place each person on a side: what the buyer says counts above what your team says,
        and what an outside adviser says depends on whom they act for.
      </p>
      {calls.length === 1 ? <Call doc={calls[0]} /> : (
        <Tabs aria-label="Calls">
          <TabList>{calls.map((c) => <Item key={c.id}>{`${c.name}${c.speakersConfirmed ? ' ✓' : ''}`}</Item>)}</TabList>
          <TabPanels>{calls.map((c) => <Item key={c.id}><div style={{ paddingTop: 16 }}><Call doc={c} /></div></Item>)}</TabPanels>
        </Tabs>
      )}
    </section>
  );
}

function Call({ doc }: { doc: Doc }) {
  const { s, setSide, acceptSides, confirmSpeakers } = useIntake();
  const [hover, setHover] = useState<string | null>(null);
  const team = new Set(s.details.team.map((t) => t.name));
  if (!doc.speakers.length) {
    return (
      <InlineAlert variant="notice">
        <Heading>No speakers found</Heading>
        <Content>Finding who speaks needs the model. This call will be read without speakers, so all of it counts as unclear. Turn the model on in the mock controls and add it again to see the full flow.</Content>
      </InlineAlert>
    );
  }
  const index = new Map(doc.speakers.map((p, i) => [p.name, i]));
  const open = doc.speakers.filter((p) => !p.side).length;
  const differs = doc.speakers.filter((p) => p.side && p.proposed && p.side !== p.proposed).length;

  return (
    <>
      <div className="call">
        <div>
          <Flex alignItems="center" gap="size-100" marginBottom="size-100">
            <strong>Transcript</strong>
            <span className="muted small">{doc.name} · {doc.date}</span>
          </Flex>
          <div className="transcript" role="list" aria-label="Transcript lines">
            {doc.transcript.map((l, i) => {
              const at = index.get(l.speaker);
              return (
                <div role="listitem" key={i} className={`tline${l.speaker ? '' : ' none'}${hover && hover === l.speaker ? ' hi' : ''}`}>
                  <span className="stripe" style={{ background: at === undefined ? 'transparent' : color(at) }} />
                  <div>
                    {l.speaker && <div className="who" style={{ color: at === undefined ? undefined : color(at) }}>{l.speaker}<span className="t">{l.time}</span></div>}
                    <div>{l.text}</div>
                    {!l.speaker && <div className="small">No one speaks this line</div>}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
        <div>
          <Flex alignItems="center" gap="size-100" marginBottom="size-100">
            <strong>People on the call</strong>
            <span className="muted small">{doc.speakers.length}</span>
            <div style={{ flex: 1 }} />
            <Button variant="secondary" isQuiet onPress={() => acceptSides(doc.id)} isDisabled={!open}>
              <MagicWand />
              <Text>Use all suggestions</Text>
            </Button>
          </Flex>
          <div className="people">
            {doc.speakers.map((p, i) => (
              <div className="person" key={p.id} onMouseEnter={() => setHover(p.name)} onMouseLeave={() => setHover(null)}>
                <span className="swatch" style={{ background: color(i) }} />
                <div style={{ minWidth: 0 }}>
                  <div className="nm">
                    {p.name}
                    {team.has(p.name) && <Badge variant="info" UNSAFE_style={{ marginLeft: 8, transform: 'scale(.85)', transformOrigin: 'left' }}>Team</Badge>}
                  </div>
                  <div className="muted small">{[p.organisation, p.title, `${p.lines} ${p.lines === 1 ? 'line' : 'lines'}`].filter(Boolean).join(' · ')}</div>
                  <div className="why">
                    <MagicWand size="XS" />
                    {p.proposed ? <span>Suggested {SIDE_LABEL[p.proposed as Exclude<Side, ''>]}: {p.why}</span> : <span>No suggestion{p.why ? `. ${p.why}` : ''}</span>}
                  </div>
                  {p.side === 'other' && (
                    <Picker label="Acts for" labelPosition="side" isQuiet selectedKey={p.actsFor || 'none'} width="size-3400" marginTop="size-50"
                      onSelectionChange={(k) => setSide(doc.id, p.id, 'other', k === 'none' ? '' : (k as 'buyer' | 'ours'))}>
                      <Item key="none">Neither side</Item>
                      <Item key="buyer">The buyer</Item>
                      <Item key="ours">Our team</Item>
                    </Picker>
                  )}
                </div>
                <ActionGroup
                  aria-label={`Side of ${p.name}`}
                  selectionMode="single"
                  selectedKeys={p.side ? [p.side] : []}
                  onSelectionChange={(k) => { const v = [...k][0]; if (v) setSide(doc.id, p.id, v as Side); }}
                  density="compact"
                  isEmphasized
                >
                  <Item key="buyer">Buyer</Item>
                  <Item key="ours">Our team</Item>
                  <Item key="other">Other</Item>
                </ActionGroup>
              </div>
            ))}
          </div>
        </div>
      </div>
      <Flex alignItems="center" gap="size-200" marginTop="size-200" UNSAFE_style={{ borderTop: '1px solid var(--spectrum-global-color-gray-300)', paddingTop: 16 }}>
        {doc.speakersConfirmed ? (
          <Flex alignItems="center" gap="size-100"><CheckmarkCircle color="positive" /><span>Speakers confirmed</span></Flex>
        ) : (
          <span className="muted small">{open ? `${open} ${open === 1 ? 'person has' : 'people have'} no side yet.` : differs ? `You changed ${differs} suggested ${differs === 1 ? 'side' : 'sides'}.` : 'All sides are set.'}</span>
        )}
        <div style={{ flex: 1 }} />
        {!doc.speakersConfirmed && (
          <Button variant="accent" isDisabled={open > 0} onPress={() => { confirmSpeakers(doc.id); ToastQueue.positive('Speakers confirmed', { timeout: 2500 }); }}>
            Confirm speakers
          </Button>
        )}
      </Flex>
    </>
  );
}
