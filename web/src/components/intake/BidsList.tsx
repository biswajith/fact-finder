import { useMemo, useState } from 'react';
import { Button, Cell, Column, Content, Flex, Heading, IllustratedMessage, Item, Picker, Row, SearchField, StatusLight, TableBody, TableHeader, TableView } from '@adobe/react-spectrum';
import Add from '@spectrum-icons/workflow/Add';
import ViewList from '@spectrum-icons/workflow/ViewList';
import type { BidFlow } from '../../bidFlow';
import { agoLabel, dateLabel, stageOf, type Stage } from '../../intake';
import { ErrorBox, Loading } from '../common';
import './intake.css';

const TONE: Record<Stage, 'notice' | 'info' | 'positive'> = { Intake: 'notice', Reading: 'info', Ready: 'positive' };

/** Every bid in the runs folder, with search and a stage filter. A row opens the bid in the wizard. */
export function BidsList({ flow }: { flow: BidFlow }) {
  const { bids, readingBid } = flow;
  const [q, setQ] = useState('');
  const [stage, setStage] = useState<string>('all');
  const rows = useMemo(() => (bids ?? [])
    .map((b) => ({ ...b, stage: stageOf(b, readingBid) }))
    .filter((b) => (stage === 'all' || b.stage === stage) && `${b.name} ${b.customer}`.toLowerCase().includes(q.trim().toLowerCase())), [bids, readingBid, q, stage]);

  return (
    <div>
      <div className="in-page-head">
        <div>
          <h1>Bids</h1>
          <div className="in-sub">Each bid holds an RFP and everything that comes with it, read together into one fact list.</div>
        </div>
        <div className="in-grow" />
        <Button variant="accent" onPress={flow.startNew}>
          <Add />
          <span>New bid</span>
        </Button>
      </div>
      {flow.bidsError && <ErrorBox message={flow.bidsError} onRetry={() => void flow.refreshBids()} />}
      {bids === null && !flow.bidsError && <Loading label="Loading bids" />}
      {bids !== null && bids.length === 0 && !flow.bidsError && (
        <section className="in-card">
          <IllustratedMessage>
            <ViewList size="XXL" />
            <Heading>No bids yet</Heading>
            <Content>Make a bid for the RFP and the documents that come with it.</Content>
          </IllustratedMessage>
        </section>
      )}
      {bids !== null && bids.length > 0 && (
        <section className="in-card" aria-label="Bids">
          <Flex gap="size-200" marginBottom="size-200" alignItems="end" wrap>
            <SearchField label="Search" value={q} onChange={setQ} width="size-3600" placeholder="Bid or customer" />
            <Picker label="Stage" selectedKey={stage} onSelectionChange={(k) => setStage(String(k))} width="size-2000">
              <Item key="all">All stages</Item>
              <Item key="Intake">Intake</Item>
              <Item key="Reading">Reading</Item>
              <Item key="Ready">Ready</Item>
            </Picker>
          </Flex>
          <TableView
            aria-label="Bids"
            density="spacious"
            height={Math.min(560, Math.max(160, 56 + rows.length * 56))}
            onAction={(k) => flow.selectBid(String(k))}
            renderEmptyState={() => <div className="in-muted">No bids match.</div>}
          >
            <TableHeader>
              <Column key="name" width="2fr" minWidth={180}>Bid</Column>
              <Column key="customer" minWidth={120}>Customer</Column>
              <Column key="due" width={120}>Due</Column>
              <Column key="docs" align="end" width={110}>Documents</Column>
              <Column key="stage" width={130}>Stage</Column>
              <Column key="updated" width={140}>Updated</Column>
            </TableHeader>
            <TableBody items={rows}>
              {(b) => (
                <Row key={b.bid_id}>
                  <Cell><strong>{b.name}</strong></Cell>
                  <Cell>{b.customer || '-'}</Cell>
                  <Cell>{dateLabel(b.due) || '-'}</Cell>
                  <Cell>{b.documents}</Cell>
                  <Cell><StatusLight variant={TONE[b.stage]}>{b.stage}</StatusLight></Cell>
                  <Cell><span className="in-muted">{agoLabel(b.modified)}</span></Cell>
                </Row>
              )}
            </TableBody>
          </TableView>
        </section>
      )}
    </div>
  );
}
