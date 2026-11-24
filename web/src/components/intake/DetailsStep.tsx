import { useMemo, useState } from 'react';
import { ActionButton, ComboBox, Content, ContextualHelp, DatePicker, Flex, Form, Heading, Item, TagGroup, Text, TextField } from '@adobe/react-spectrum';
import { parseDate } from '@internationalized/date';
import Add from '@spectrum-icons/workflow/Add';
import * as api from '../../api';
import type { BidFlow } from '../../bidFlow';
import { customersOf, peopleOf } from '../../intake';
import { useAsync } from '../../hooks';
import './intake.css';

/** The teams of the other bids, to suggest names; a bid that cannot be read is left out. */
function useKnownPeople(flow: BidFlow) {
  const others = (flow.bids ?? []).filter((b) => b.bid_id !== flow.bidId).slice(0, 25).map((b) => b.bid_id);
  const known = useAsync<{ name: string; role: string }[][]>(
    async (signal) => (await Promise.all(others.map((id) => api.getBid(id, signal).then((b) => b.team, () => [])))),
    [others.join('|')],
    others.length > 0,
  );
  return known.data ?? [];
}

/** Step 1: what the bid is, and who is on our side. */
export function DetailsStep({ flow }: { flow: BidFlow }) {
  const { details: d, setDetails } = flow;
  const [pick, setPick] = useState('');
  const [role, setRole] = useState('');
  const customers = useMemo(() => customersOf(flow.bids).map((c) => ({ id: c })), [flow.bids]);
  const teams = useKnownPeople(flow);
  const available = useMemo(() => peopleOf(teams, d.team.map((t) => t.name)), [teams, d.team]);
  const edit = (patch: Partial<typeof d>) => setDetails((cur) => ({ ...cur, ...patch }));

  const add = (name: string, withRole: string) => {
    const n = name.trim();
    if (!n) return;
    if (!d.team.some((t) => t.name.toLowerCase() === n.toLowerCase())) edit({ team: [...d.team, { name: n, role: withRole.trim() }] });
    setPick('');
    setRole('');
  };
  const made = !!flow.bid;

  return (
    <>
      <section className="in-card" aria-labelledby="details-h">
        <h2 id="details-h">Bid details</h2>
        <p className="in-lede">What this opportunity is. Only the name is needed to go on.</p>
        <Form maxWidth="size-6000" validationBehavior="aria" onSubmit={(e) => e.preventDefault()}>
          <TextField label="Bid name" isRequired autoFocus={!made} value={d.name} onChange={(v) => edit({ name: v })}
            description="How your team will find it, e.g. the RFP title." />
          <ComboBox label="Customer" allowsCustomValue defaultItems={customers} inputValue={d.customer} onInputChange={(v) => edit({ customer: v })}
            description="Pick a customer from your other bids or type a new one.">
            {(c) => <Item key={c.id}>{c.id}</Item>}
          </ComboBox>
          <Flex gap="size-200" wrap>
            <TextField label="CRM ID" value={d.deal_id} onChange={(v) => edit({ deal_id: v })} placeholder="OPP-00000" width="size-2400"
              isReadOnly={made} description={made ? 'Set when the bid was made' : undefined} />
            <DatePicker label="Proposal due" value={d.due ? parseDate(d.due) : null} onChange={(v) => edit({ due: v ? v.toString() : null })} width="size-2400"
              contextualHelp={(
                <ContextualHelp variant="info">
                  <Heading>Due date</Heading>
                  <Content>The date your team plans for. It is kept as you enter it: a document that moves the deadline does not change this field.</Content>
                </ContextualHelp>
              )} />
          </Flex>
        </Form>
      </section>

      <section className="in-card" aria-labelledby="team-h">
        <h2 id="team-h">Your team</h2>
        <p className="in-lede">People on your side. In a call, anyone on this list is proposed as speaking for your team.</p>
        <Flex gap="size-150" alignItems="end" marginBottom="size-200" wrap>
          <ComboBox label="Add a person" allowsCustomValue defaultItems={available} inputValue={pick} onInputChange={setPick}
            onSelectionChange={(k) => {
              if (k === null) return;
              const p = available.find((x) => x.name === String(k));
              if (p) add(p.name, p.role);
            }} width="size-3600" menuTrigger="focus">
            {(p) => <Item key={p.name} textValue={p.name}><Text>{p.name}</Text><Text slot="description">{p.role || 'No role given'}</Text></Item>}
          </ComboBox>
          <TextField label="Role (optional)" value={role} onChange={setRole} width="size-2400" />
          <ActionButton onPress={() => add(pick, role)} isDisabled={!pick.trim()} aria-label="Add person"><Add /></ActionButton>
        </Flex>
        <TagGroup
          aria-label="Team"
          items={d.team.map((t) => ({ ...t, id: t.name }))}
          onRemove={(keys) => edit({ team: d.team.filter((t) => !keys.has(t.name)) })}
          renderEmptyState={() => <span className="in-muted">No one yet.</span>}
        >
          {(t) => <Item key={t.id} textValue={t.name}>{t.role ? `${t.name} · ${t.role}` : t.name}</Item>}
        </TagGroup>
        <p className="in-notice in-muted">Names are matched exactly to the speakers of a call. Saving the team proposes sides again for calls whose speakers are not confirmed.</p>
      </section>
    </>
  );
}
