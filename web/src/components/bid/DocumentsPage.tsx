import { useState } from 'react';
import { Button, Item, Picker, TextField } from '@adobe/react-spectrum';
import { rowsInOrder } from '../../bid';
import type { BidFlow } from '../../bidFlow';
import type { Status } from '../../types';
import { ErrorBox, Loading } from '../common';
import { PageHeader } from '../shell/PageHeader';
import '../pages.css';
import { DocumentsTable } from './DocumentsTable';
import { DropZone } from './DropZone';
import { PlanAndStart } from './PlanAndStart';
import { PrecedenceOrder } from './PrecedenceOrder';
import { TeamList } from './TeamList';

function NewBid({ flow }: { flow: BidFlow }) {
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const create = async () => {
    if (!name.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      await flow.createBid(name);
      setName('');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="pg-form-row" onSubmit={(e) => { e.preventDefault(); void create(); }}>
      <TextField label="New bid" placeholder="Name of the bid" value={name} onChange={setName} />
      <div className="pg-form-btn"><Button type="submit" variant="secondary" isDisabled={!name.trim() || busy}>Create</Button></div>
      {error && <div role="alert" className="pg-bad wrap-text">{error}</div>}
    </form>
  );
}

/** Documents: pick or start a bid, add its documents, say what each one is, then read them together. */
export function DocumentsPage({ flow, status }: { flow: BidFlow; status: Status | null }) {
  const { bid, bids, bidId } = flow;
  const docs = bid ? rowsInOrder(bid) : [];
  return (
    <>
      <PageHeader title="Documents" subtitle="The documents of a bid, read together into one fact list" />
      <div className="pg-stack">
        {flow.bidsError && <ErrorBox message={flow.bidsError} onRetry={() => void flow.refreshBids()} />}
        <section className="pg-form" aria-label="Bid">
          {bids && bids.length > 0 && (
            <Picker
              label="Bid"
              items={bids}
              selectedKey={bidId}
              onSelectionChange={(k) => k != null && flow.selectBid(String(k))}
              width="size-4600"
            >
              {(b) => <Item key={b.bid_id}>{`${b.name} · ${b.documents} ${b.documents === 1 ? 'document' : 'documents'}`}</Item>}
            </Picker>
          )}
          <NewBid flow={flow} />
        </section>
        {bids === null && !flow.bidsError && <Loading label="Loading bids" />}
        {bidId && flow.bidError && <ErrorBox message={flow.bidError} onRetry={() => void flow.reload()} />}
        {bid && (
          <>
            <DropZone onFiles={flow.addFiles} />
            <DocumentsTable bid={bid} uploads={flow.uploads} onDismiss={flow.dismissUpload} onPatch={flow.patchDocument} onRemove={flow.removeDocument} />
            <TeamList key={bid.bid_id + JSON.stringify(bid.team)} team={bid.team} onSave={flow.saveTeam} />
            <PrecedenceOrder
              key={bid.bid_id + docs.map((d) => `${d.doc_id}:${d.playbook}`).join() + JSON.stringify(bid.precedence)}
              bid={bid}
              onSet={flow.setPrecedence}
            />
            <PlanAndStart flow={flow} bid={bid} status={status} />
          </>
        )}
      </div>
    </>
  );
}
