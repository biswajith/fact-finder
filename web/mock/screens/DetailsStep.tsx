import { useState } from 'react';
import { ActionButton, ComboBox, ContextualHelp, Content, DatePicker, Flex, Form, Heading, Item, TagGroup, Text, TextField } from '@adobe/react-spectrum';
import { parseDate } from '@internationalized/date';
import Add from '@spectrum-icons/workflow/Add';
import { CUSTOMERS, PEOPLE } from '../data';
import { useIntake } from '../store';

export function DetailsStep() {
  const { s, setDetails } = useIntake();
  const d = s.details;
  const [pick, setPick] = useState<string>('');
  const available = PEOPLE.filter((p) => !d.team.some((t) => t.name === p.name));
  const add = (name: string) => {
    const p = PEOPLE.find((x) => x.name === name) ?? (name.trim() ? { name: name.trim(), role: 'Team member' } : null);
    if (p && !d.team.some((t) => t.name.toLowerCase() === p.name.toLowerCase())) setDetails({ team: [...d.team, p] });
    setPick('');
  };

  return (
    <>
      <section className="card" aria-labelledby="details-h">
        <h2 id="details-h">Bid details</h2>
        <p className="lede">What this opportunity is. Only the name and the customer are needed to go on.</p>
        <Form maxWidth="size-6000" validationBehavior="aria" onSubmit={(e) => e.preventDefault()}>
          <TextField label="Bid name" isRequired autoFocus value={d.name} onChange={(v) => setDetails({ name: v })}
            description="How your team will find it, e.g. the RFP title." />
          <ComboBox label="Customer" isRequired allowsCustomValue defaultItems={CUSTOMERS.map((c) => ({ id: c }))}
            inputValue={d.customer} onInputChange={(v) => setDetails({ customer: v })}>
            {(c) => <Item key={c.id}>{c.id}</Item>}
          </ComboBox>
          <Flex gap="size-200" wrap>
            <TextField label="CRM opportunity" value={d.dealId} onChange={(v) => setDetails({ dealId: v })} placeholder="OPP-00000" width="size-2400" />
            <DatePicker label="Proposal due" value={d.due ? parseDate(d.due) : null} onChange={(v) => setDetails({ due: v ? v.toString() : null })} width="size-2400"
              contextualHelp={(
                <ContextualHelp variant="info">
                  <Heading>Due date</Heading>
                  <Content>The date your team plans for. When an addendum moves the deadline, the fact list will say so; this field does not change by itself.</Content>
                </ContextualHelp>
              )} />
          </Flex>
        </Form>
      </section>

      <section className="card" aria-labelledby="team-h">
        <h2 id="team-h">Your team</h2>
        <p className="lede">People on your side. In a call, anyone on this list is proposed as speaking for your team.</p>
        <Flex gap="size-150" alignItems="end" marginBottom="size-200">
          <ComboBox label="Add a person" allowsCustomValue defaultItems={available} inputValue={pick} onInputChange={setPick}
            onSelectionChange={(k) => k && add(String(k))} width="size-3600" menuTrigger="focus">
            {(p) => <Item key={p.name} textValue={p.name}><Text>{p.name}</Text><Text slot="description">{p.role}</Text></Item>}
          </ComboBox>
          <ActionButton onPress={() => add(pick)} isDisabled={!pick.trim()} aria-label="Add person"><Add /></ActionButton>
        </Flex>
        <TagGroup aria-label="Team" items={d.team.map((t) => ({ ...t, id: t.name }))} onRemove={(keys) => setDetails({ team: d.team.filter((t) => !keys.has(t.name)) })}
          renderEmptyState={() => <span className="muted">No one yet.</span>}>
          {(t) => <Item key={t.id} textValue={t.name}>{`${t.name} · ${t.role}`}</Item>}
        </TagGroup>
      </section>
    </>
  );
}
