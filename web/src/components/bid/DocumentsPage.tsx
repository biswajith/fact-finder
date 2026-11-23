import { useEffect, useRef, type ReactNode } from 'react';
import { Button, Item, Picker } from '@adobe/react-spectrum';
import { rowsInOrder, showPrecedence, showTeam } from '../../bid';
import type { BidFlow } from '../../bidFlow';
import type { Status } from '../../types';
import { ErrorBox, Loading } from '../common';
import { PageHeader } from '../shell/PageHeader';
import '../pages.css';
import { DocumentsTable } from './DocumentsTable';
import { DropZone } from './DropZone';
import { NewBidScreen } from './NewBidScreen';
import { PlanAndStart } from './PlanAndStart';
import { PrecedenceOrder } from './PrecedenceOrder';
import { TeamList } from './TeamList';

function Step({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  const id = `step-${n}`;
  return (
    <section className="pg-stack" aria-labelledby={id}>
      <div className="pg-step">
        <span className="pg-step-n" aria-hidden>{n}</span>
        <h2 className="pg-h2" id={id}>{title}</h2>
      </div>
      {children}
    </section>
  );
}

/** Documents: make a bid, add its documents, say what each one is, then read them together. */
export function DocumentsPage({ flow, status }: { flow: BidFlow; status: Status | null }) {
  const { bid, bids, bidId, creating } = flow;
  const root = useRef<HTMLDivElement>(null);
  const wasCreating = useRef(false);
  // After a bid is made, focus moves to its heading.
  useEffect(() => {
    if (creating) {
      wasCreating.current = true;
      return;
    }
    if (wasCreating.current && bid && bid.bid_id === bidId) {
      wasCreating.current = false;
      const h = root.current?.querySelector('h1');
      if (h) {
        h.tabIndex = -1;
        h.focus();
      }
    }
  }, [creating, bid, bidId]);

  if (creating) return <NewBidScreen flow={flow} />;

  const docs = bid ? rowsInOrder(bid) : [];
  const subtitle = !bid ? undefined : docs.length === 0 ? 'No documents yet' : `${docs.length} ${docs.length === 1 ? 'document' : 'documents'}`;
  const actions = (
    <>
      {bids && bids.length >= 2 && (
        <Picker aria-label="Bid" items={bids} selectedKey={bidId} onSelectionChange={(k) => k != null && flow.selectBid(String(k))} width="size-3000">
          {(b) => <Item key={b.bid_id}>{b.name}</Item>}
        </Picker>
      )}
      <Button variant="accent" style="outline" onPress={flow.startNew}>New bid</Button>
    </>
  );
  const needsConfirm = !!bid && !bid.run && !bid.documents.some((d) => d.confirmed);
  return (
    <div ref={root}>
      <PageHeader title={bid ? bid.name : (bids?.find((b) => b.bid_id === bidId)?.name ?? 'Documents')} subtitle={subtitle} actions={actions} />
      <div className="pg-steps-page">
        {flow.bidsError && <ErrorBox message={flow.bidsError} onRetry={() => void flow.refreshBids()} />}
        {(bids === null || (bidId && !bid && !flow.bidError)) && !flow.bidsError && <Loading label="Loading bid" />}
        {bidId && flow.bidError && <ErrorBox message={flow.bidError} onRetry={() => void flow.reload()} />}
        {bid && (
          <>
            <Step n={1} title="Add documents">
              <DropZone onFiles={flow.addFiles} title={null} />
            </Step>
            <Step n={2} title="Check each document">
              {docs.length === 0 && flow.uploads.length === 0 ? (
                <div className="pg-note">Add a document above to start.</div>
              ) : (
                <DocumentsTable bid={bid} uploads={flow.uploads} onDismiss={flow.dismissUpload} onPatch={flow.patchDocument} onSuggest={flow.suggestSpeakers} hasKey={!!status?.has_key} onRemove={flow.removeDocument} />
              )}
            </Step>
            {showTeam(bid) && (
              <TeamList
                key={bid.bid_id + JSON.stringify(bid.team)}
                team={bid.team}
                onSave={flow.saveTeam}
                open={bid.documents.some((d) => d.playbook === 'call-transcript' && d.speakers_confirmed === false)}
              />
            )}
            {showPrecedence(bid) && (
              <PrecedenceOrder
                key={bid.bid_id + docs.map((d) => `${d.doc_id}:${d.playbook}`).join() + JSON.stringify(bid.precedence)}
                bid={bid}
                onSet={flow.setPrecedence}
              />
            )}
            <Step n={3} title="Extract">
              {needsConfirm && <div className="pg-note">Confirm at least one document in step 2.</div>}
              {docs.length > 0 && <PlanAndStart flow={flow} bid={bid} status={status} />}
            </Step>
          </>
        )}
      </div>
    </div>
  );
}
