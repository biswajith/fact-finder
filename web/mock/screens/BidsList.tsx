import { useMemo, useState } from 'react';
import { Button, Cell, Column, Flex, Item, Picker, Row, SearchField, StatusLight, TableBody, TableHeader, TableView, ToastQueue } from '@adobe/react-spectrum';
import Add from '@spectrum-icons/workflow/Add';
import { EXISTING_BIDS, type BidSummary } from '../data';
import { useIntake } from '../store';

const STAGE: Record<BidSummary['stage'], 'notice' | 'info' | 'positive' | 'neutral'> = { Intake: 'notice', Reading: 'info', Ready: 'positive', Submitted: 'neutral' };

export function BidsList() {
  const { s, view, reset, loadSample } = useIntake();
  const [q, setQ] = useState('');
  const [stage, setStage] = useState<string>('all');
  const draft: BidSummary[] = s.docs.length || s.details.name
    ? [{ id: 'draft', name: s.details.name || 'Untitled bid', customer: s.details.customer || '-', due: s.details.due ?? '-', documents: s.docs.length,
        stage: s.run?.done ? 'Ready' : s.run ? 'Reading' : 'Intake', owner: s.details.owner, updated: 'just now' }]
    : [];
  const rows = useMemo(() => [...draft, ...EXISTING_BIDS].filter((b) =>
    (stage === 'all' || b.stage === stage) && `${b.name} ${b.customer} ${b.owner}`.toLowerCase().includes(q.toLowerCase())), [q, stage, draft]);

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Bids</h1>
          <div className="sub">Every opportunity your team is reading, from intake to submission.</div>
        </div>
        <div className="grow" />
        <Button variant="secondary" style="outline" onPress={loadSample}>Open sample bid</Button>
        <Button variant="accent" onPress={() => { if (!draft.length) reset(); view('intake'); }}>
          <Add />
          <span>{draft.length ? 'Continue draft' : 'New bid'}</span>
        </Button>
      </div>
      <div className="card">
        <Flex gap="size-200" marginBottom="size-200" alignItems="end">
          <SearchField label="Search" value={q} onChange={setQ} width="size-3600" placeholder="Bid, customer or owner" />
          <Picker label="Stage" selectedKey={stage} onSelectionChange={(k) => setStage(String(k))} width="size-2000">
            <Item key="all">All stages</Item>
            <Item key="Intake">Intake</Item>
            <Item key="Reading">Reading</Item>
            <Item key="Ready">Ready</Item>
            <Item key="Submitted">Submitted</Item>
          </Picker>
        </Flex>
        <TableView
          aria-label="Bids"
          density="spacious"
          height={Math.min(560, 56 + rows.length * 56)}
          onAction={(k) => (k === 'draft' ? view('intake') : ToastQueue.neutral('Opening an existing bid is not part of this mock', { timeout: 3000 }))}
          renderEmptyState={() => <div className="muted">No bids match.</div>}
        >
          <TableHeader>
            <Column key="name" width="2fr" allowsSorting={false}>Bid</Column>
            <Column key="customer">Customer</Column>
            <Column key="due">Due</Column>
            <Column key="docs" align="end" width={110}>Documents</Column>
            <Column key="stage" width={140}>Stage</Column>
            <Column key="owner">Owner</Column>
            <Column key="updated" width={130}>Updated</Column>
          </TableHeader>
          <TableBody items={rows}>
            {(b) => (
              <Row key={b.id}>
                <Cell><strong>{b.name}</strong>{b.id === 'draft' ? <span className="muted"> · draft</span> : null}</Cell>
                <Cell>{b.customer}</Cell>
                <Cell>{b.due}</Cell>
                <Cell>{b.documents}</Cell>
                <Cell><StatusLight variant={STAGE[b.stage]}>{b.stage}</StatusLight></Cell>
                <Cell>{b.owner}</Cell>
                <Cell><span className="muted">{b.updated}</span></Cell>
              </Row>
            )}
          </TableBody>
        </TableView>
      </div>
    </div>
  );
}
