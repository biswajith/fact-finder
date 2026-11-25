import type { ReactNode } from 'react';
import { ActionButton, Breadcrumbs, Button, Item, SearchField, ToastQueue, Tooltip, TooltipTrigger } from '@adobe/react-spectrum';
import Bell from '@spectrum-icons/workflow/Bell';
import Data from '@spectrum-icons/workflow/Data';
import Help from '@spectrum-icons/workflow/Help';
import TableAndChart from '@spectrum-icons/workflow/TableAndChart';
import ViewList from '@spectrum-icons/workflow/ViewList';
import Alert from '@spectrum-icons/workflow/Alert';
import { EXISTING_BIDS, missing, typeInfo } from './data';
import { MockControls } from './MockControls';
import { BidsList } from './screens/BidsList';
import { DetailsStep } from './screens/DetailsStep';
import { DocumentsStep } from './screens/DocumentsStep';
import { ReviewStep } from './screens/ReviewStep';
import { RunStep } from './screens/RunStep';
import { SpeakersStep } from './screens/SpeakersStep';
import { useIntake, type Step } from './store';

function NavItem({ icon, label, current, count, onPress }: { icon: ReactNode; label: string; current?: boolean; count?: number; onPress: () => void }) {
  return (
    <button className="navitem" aria-current={current ? 'page' : undefined} onClick={onPress}>
      {icon}
      {label}
      {count !== undefined && <span className="count">{count}</span>}
    </button>
  );
}

const notInMock = (what: string) => ToastQueue.neutral(`${what} is not part of this mock`, { timeout: 3000 });

export function App() {
  const { s, view } = useIntake();
  return (
    <div className="app">
      <header className="topbar">
        <div className="brand"><span className="brand-mark" aria-hidden>R</span>RFP Facts</div>
        <span className="mock-chip" title="Nothing here calls a server or a model">Mock</span>
        <MockControls />
        <div className="grow" />
        <SearchField aria-label="Search bids, documents and facts" isQuiet width="size-3600" placeholder="Search bids, documents, facts" onSubmit={() => notInMock('Search')} />
        <TooltipTrigger>
          <ActionButton isQuiet aria-label="Notifications" onPress={() => notInMock('Notifications')}><Bell /></ActionButton>
          <Tooltip>Notifications</Tooltip>
        </TooltipTrigger>
        <TooltipTrigger>
          <ActionButton isQuiet aria-label="Help" onPress={() => notInMock('Help')}><Help /></ActionButton>
          <Tooltip>Help</Tooltip>
        </TooltipTrigger>
        <span className="avatar" aria-label="Signed in as Tom Okafor" role="img">TO</span>
      </header>
      <div className="body">
        <nav className="sidenav" aria-label="Main">
          <div className="sidenav-title">Workspace</div>
          <NavItem icon={<ViewList size="S" />} label="Bids" current count={EXISTING_BIDS.length + (s.docs.length || s.details.name ? 1 : 0)} onPress={() => view('bids')} />
          <NavItem icon={<Data size="S" />} label="Fact lists" onPress={() => notInMock('Fact lists')} />
          <NavItem icon={<Alert size="S" />} label="Conflicts" onPress={() => notInMock('Conflicts')} />
          <NavItem icon={<TableAndChart size="S" />} label="Reports" onPress={() => notInMock('Reports')} />
        </nav>
        <main className="main" id="main">
          {s.view === 'bids' ? <BidsList /> : <Intake />}
        </main>
      </div>
    </div>
  );
}

// --- the intake wizard ------------------------------------------------------------------------------

interface StepInfo { key: Step; title: string; sub: string; state: 'done' | 'current' | 'todo' | 'skipped'; enabled: boolean }

function useSteps(): { steps: StepInfo[]; canNext: boolean; blocker: string; summary: string } {
  const { s } = useIntake();
  const order: Step[] = ['details', 'documents', 'speakers', 'review', 'run'];
  const at = order.indexOf(s.step);
  const confirmed = s.docs.filter((d) => d.confirmed);
  const working = s.docs.filter((d) => ['uploading', 'reading', 'classifying', 'speakers'].includes(d.phase));
  const calls = confirmed.filter((d) => typeInfo(d.type).spoken);
  const callsOpen = calls.filter((d) => d.speakers.length && !d.speakersConfirmed);
  const detailsOk = !!s.details.name.trim() && !!s.details.customer.trim();
  const docsOk = confirmed.length > 0 && working.length === 0 && confirmed.every((d) => missing(d).filter((m) => m !== 'Speakers').length === 0);
  const speakersOk = callsOpen.length === 0;
  const started = !!s.run;

  const sub: Record<Step, string> = {
    details: detailsOk ? `${s.details.customer}${s.details.due ? ` · due ${s.details.due}` : ''}` : 'Name, customer, team',
    documents: s.docs.length ? `${confirmed.length} of ${s.docs.length} confirmed` : 'Upload and check each one',
    speakers: calls.length === 0 ? 'No calls in this bid' : `${calls.length - callsOpen.length} of ${calls.length} calls confirmed`,
    review: started ? 'Started' : 'Order, cost, start',
    run: s.run?.done ? 'Finished' : started ? 'Running' : 'Not started',
  };
  const ok: Record<Step, boolean> = { details: detailsOk, documents: docsOk, speakers: calls.length > 0 && speakersOk, review: started, run: !!s.run?.done };
  const titles: Record<Step, string> = { details: 'Bid details', documents: 'Documents', speakers: 'Call speakers', review: 'Review and start', run: 'Extraction' };
  const steps = order.map((key, i): StepInfo => ({
    key, title: titles[key], sub: sub[key],
    state: key === s.step ? 'current' : key === 'speakers' && calls.length === 0 && i < at ? 'skipped' : i < at || ok[key] ? 'done' : 'todo',
    enabled: started ? key === 'run' || i < at : i <= at || order.slice(0, i).every((k) => ok[k] || (k === 'speakers' && calls.length === 0)),
  }));
  let blocker = '';
  if (s.step === 'details' && !detailsOk) blocker = 'Add a bid name and a customer to continue.';
  if (s.step === 'documents') {
    if (working.length) blocker = `Reading ${working.length} ${working.length === 1 ? 'document' : 'documents'}...`;
    else if (!confirmed.length) blocker = s.docs.length ? 'Confirm at least one document to continue.' : 'Add the RFP and anything that came with it.';
    else if (!docsOk) blocker = 'A confirmed document is missing its issue date or number.';
  }
  if (s.step === 'speakers' && !speakersOk) blocker = `Confirm the speakers of ${callsOpen.length === 1 ? 'the call' : `${callsOpen.length} calls`}.`;
  const canNext = s.step === 'details' ? detailsOk : s.step === 'documents' ? docsOk : s.step === 'speakers' ? speakersOk : false;
  const unconfirmed = s.docs.length - confirmed.length;
  const summary = s.step === 'documents' && confirmed.length && unconfirmed && !blocker
    ? `${unconfirmed} unconfirmed ${unconfirmed === 1 ? 'document is' : 'documents are'} left out of this run.` : '';
  return { steps, canNext, blocker, summary };
}

function Rail({ steps }: { steps: StepInfo[] }) {
  const { go } = useIntake();
  return (
    <nav className="rail" aria-label="Intake steps">
      {steps.map((st, i) => (
        <button
          key={st.key}
          className={`rail-step ${st.state}`}
          aria-current={st.state === 'current' ? 'step' : undefined}
          aria-disabled={!st.enabled}
          aria-label={`Step ${i + 1}, ${st.title}: ${st.sub}`}
          onClick={() => st.enabled && go(st.key)}
        >
          <span className="dot" aria-hidden>{st.state === 'done' || (st.key === 'run' && st.sub === 'Finished') ? '✓' : st.state === 'skipped' ? '–' : i + 1}</span>
          <span>
            <div className="rail-title">{st.title}</div>
            <div className="rail-sub">{st.sub}</div>
          </span>
        </button>
      ))}
    </nav>
  );
}

function Intake() {
  const { s, go, view } = useIntake();
  const { steps, canNext, blocker, summary } = useSteps();
  const order = steps.map((x) => x.key);
  const at = order.indexOf(s.step);
  const hasCalls = s.docs.some((d) => d.confirmed && typeInfo(d.type).spoken);
  const next = () => {
    let to = order[at + 1];
    if (to === 'speakers' && !hasCalls) to = 'review';
    go(to);
    document.getElementById('main')?.scrollTo({ top: 0 });
  };
  const back = () => {
    let to = order[at - 1];
    if (to === 'speakers' && !hasCalls) to = 'documents';
    go(to);
  };
  const body = { details: <DetailsStep />, documents: <DocumentsStep />, speakers: <SpeakersStep />, review: <ReviewStep />, run: <RunStep /> }[s.step];
  const showFooter = s.step !== 'run' && s.step !== 'review';

  return (
    <div className="page">
      <Breadcrumbs onAction={(k) => k === 'bids' && view('bids')}>
        <Item key="bids">Bids</Item>
        <Item key="new">{s.details.name.trim() || 'New bid'}</Item>
      </Breadcrumbs>
      <div className="page-head">
        <div>
          <h1>{s.details.name.trim() || 'New bid'}</h1>
          <div className="sub">{[s.details.customer, s.details.dealId && `CRM ${s.details.dealId}`, s.details.due && `Due ${s.details.due}`].filter(Boolean).join(' · ') || 'Set up a bid: its details, its documents, then read them into one fact list.'}</div>
        </div>
        <div className="grow" />
        {!s.run && (
          <Button variant="secondary" style="outline" onPress={() => { ToastQueue.neutral('Draft saved. You can come back to it from Bids.', { timeout: 4000 }); view('bids'); }}>
            Save draft and close
          </Button>
        )}
      </div>
      <div className="wizard">
        <Rail steps={steps} />
        <div>{body}</div>
      </div>
      {showFooter && (
        <div className="footer">
          <div className="footer-in">
            {at > 0 && <Button variant="secondary" style="outline" onPress={back}>Back</Button>}
            <div className="grow" />
            <span className="muted small" role="status">{blocker || summary}</span>
            <Button variant="accent" isDisabled={!canNext} onPress={next}>
              {s.step === 'documents' && !hasCalls ? 'Next: review' : s.step === 'documents' ? 'Next: speakers' : s.step === 'speakers' ? 'Next: review' : 'Next: documents'}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
