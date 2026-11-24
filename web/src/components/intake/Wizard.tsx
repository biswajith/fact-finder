import { useCallback } from 'react';
import { Breadcrumbs, Button, Item, ToastQueue } from '@adobe/react-spectrum';
import type { BidFlow } from '../../bidFlow';
import { dateLabel, STEP_ORDER, wizard, type Step, type StepInfo } from '../../intake';
import type { Status } from '../../types';
import { ErrorBox, Loading } from '../common';
import { DetailsStep } from './DetailsStep';
import { DocumentsStep } from './DocumentsStep';
import { ReviewStep } from './ReviewStep';
import { RunStep } from './RunStep';
import { SpeakersStep } from './SpeakersStep';
import { scrollToTop } from './parts';
import './intake.css';

/** The steps down the left: done, current, to do; a step the reader may not reach yet is dimmed. */
function Rail({ steps, onGo }: { steps: StepInfo[]; onGo: (step: Step) => void }) {
  return (
    <nav className="in-rail" aria-label="Intake steps">
      {steps.map((st, i) => (
        <button
          key={st.key}
          type="button"
          className={`in-rail-step ${st.state}`}
          aria-current={st.state === 'current' ? 'step' : undefined}
          aria-disabled={!st.enabled}
          aria-label={`Step ${i + 1}, ${st.title}: ${st.sub}`}
          onClick={() => st.enabled && onGo(st.key)}
        >
          <span className="in-dot" aria-hidden>{st.state === 'done' || (st.key === 'run' && st.sub === 'Finished') ? '✓' : st.state === 'skipped' ? '–' : i + 1}</span>
          <span>
            <div className="in-rail-title">{st.title}</div>
            <div className="in-rail-sub">{st.sub}</div>
          </span>
        </button>
      ))}
    </nav>
  );
}

/** One bid, step by step: details, documents, call speakers, review, run. */
export function Wizard({ flow, status }: { flow: BidFlow; status: Status | null }) {
  const { bid, details: d, step, job } = flow;
  const pending = flow.uploads.filter((u) => u.status === 'pending').length;
  const w = wizard({ step, bid, name: d.name, customer: d.customer, due: d.due, pending, job });
  const title = d.name.trim() || bid?.name || 'New bid';
  const crm = bid && d.deal_id !== bid.bid_id ? d.deal_id : '';
  const sub = [d.customer.trim(), crm && `CRM ${crm}`, d.due && `Due ${dateLabel(d.due)}`].filter(Boolean).join(' · ')
    || 'Set up a bid: its details, its documents, then read them into one fact list.';

  /** Leaving the details step makes the bid (or saves its changes); a failure keeps the reader there. */
  const go = useCallback(async (to: Step) => {
    if (step === 'details' && to !== 'details' && (flow.drafting || flow.detailsChanged)) {
      if (!(await flow.saveDetails())) return;
    }
    flow.setStep(to);
    scrollToTop();
  }, [flow, step]);
  const at = STEP_ORDER.indexOf(step);
  const next = () => {
    let to = STEP_ORDER[at + 1];
    if (to === 'speakers' && !w.hasCalls) to = 'review';
    void go(to);
  };
  const back = () => {
    let to = STEP_ORDER[at - 1];
    if (to === 'speakers' && !w.hasCalls) to = 'documents';
    void go(to);
  };
  /** Back to the list; what was typed on the details step is kept when there is a name. */
  const leave = async (message?: string) => {
    if (d.name.trim() && (flow.drafting || (step === 'details' && flow.detailsChanged))) {
      if (!(await flow.saveDetails())) return;
      if (message) ToastQueue.neutral(message, { timeout: 4000 });
    }
    flow.closeBid();
    scrollToTop();
  };

  const body = {
    details: <DetailsStep flow={flow} />,
    documents: <DocumentsStep flow={flow} status={status} />,
    speakers: <SpeakersStep flow={flow} status={status} />,
    review: <ReviewStep flow={flow} status={status} />,
    run: <RunStep flow={flow} />,
  }[step];
  const waitingForBid = flow.bidId !== null && !bid && step !== 'details';
  const showFooter = step === 'details' || step === 'documents' || step === 'speakers';

  return (
    <div>
      <Breadcrumbs onAction={(k) => k === 'bids' && void leave()}>
        <Item key="bids">Bids</Item>
        <Item key="bid">{title}</Item>
      </Breadcrumbs>
      <div className="in-page-head">
        <div>
          <h1>{title}</h1>
          <div className="in-sub">{sub}</div>
        </div>
        <div className="in-grow" />
        {!job && (
          <Button variant="secondary" style="outline" isDisabled={!d.name.trim()} onPress={() => void leave('Draft saved. You can come back to it from Bids.')}>
            Save draft and close
          </Button>
        )}
      </div>
      {flow.bidError && <ErrorBox message={flow.bidError} onRetry={() => void flow.reload()} />}
      <div className="in-wizard">
        <Rail steps={w.steps} onGo={(s) => void go(s)} />
        <div className="in-step">{waitingForBid && !flow.bidError ? <Loading label="Loading bid" /> : body}</div>
      </div>
      {showFooter && (
        <div className="in-footer">
          <div className="in-footer-in">
            {at > 0 && <Button variant="secondary" style="outline" onPress={back}>Back</Button>}
            <div className="in-grow" />
            <span className="in-muted in-small" role="status">{w.blocker || w.summary}</span>
            <Button variant="accent" isDisabled={!w.canNext} onPress={next}>{step === 'details' ? 'Next: documents' : step === 'documents' && w.hasCalls ? 'Next: speakers' : 'Next: review'}</Button>
          </div>
        </div>
      )}
    </div>
  );
}
