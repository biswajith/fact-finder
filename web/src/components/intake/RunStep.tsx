import {
  Button, Content, Disclosure, DisclosurePanel, DisclosureTitle, Flex, Heading, IllustratedMessage, InlineAlert, ProgressBar, ProgressCircle, StatusLight,
} from '@adobe/react-spectrum';
import CheckmarkCircle from '@spectrum-icons/workflow/CheckmarkCircle';
import * as api from '../../api';
import { rowsInOrder } from '../../bid';
import type { BidFlow } from '../../bidFlow';
import { useAsync } from '../../hooks';
import { BID_STEPS, clock, docRunState, jobProgress, runningNow, STEP_NAMES, type RunState } from '../../intake';
import type { BidDocument, JobStep } from '../../types';
import { FileBadge } from './parts';
import './intake.css';

function TaskLine({ s }: { s: JobStep }) {
  const name = `${STEP_NAMES[s.step] ?? s.step}${s.status === 'reused' ? ' (reused)' : ''}`;
  return (
    <div className={`in-task ${s.status}`}>
      {s.status === 'done' || s.status === 'reused' ? <CheckmarkCircle size="S" color="positive" aria-label="done" />
        : s.status === 'running' ? <ProgressCircle size="S" isIndeterminate aria-label="running" />
        : <span aria-label="failed" style={{ color: 'var(--spectrum-global-color-red-700)', fontWeight: 700 }}>✗</span>}
      <span>{name}</span>
      <span className="in-muted in-small">{s.status === 'running' ? 'running' : ''}</span>
      {s.status === 'failed' && s.detail && <span className="in-bad in-small">{s.detail}</span>}
    </div>
  );
}

const latest = (steps: JobStep[]) => {
  const seen = new Map<string, JobStep>();
  for (const s of steps) seen.set(s.step, s);
  return [...seen.values()];
};

function Light({ state }: { state: RunState }) {
  if (state === 'failed') return <StatusLight variant="negative">Failed</StatusLight>;
  if (state === 'done') return <StatusLight variant="positive">Read</StatusLight>;
  if (state === 'running') return <StatusLight variant="info">Reading</StatusLight>;
  return <StatusLight variant="neutral">Waiting</StatusLight>;
}

/** Step 5: the extraction as it runs, document by document, and what it made. */
export function RunStep({ flow }: { flow: BidFlow }) {
  const { bid, job } = flow;
  const done = job?.status === 'done';
  const runPath = job?.run || bid?.run || '';
  // The facts of each document, counted from the fact list once it is built.
  const facts = useAsync(async () => {
    const r = await api.getFacts(runPath, false);
    const by = new Map<number, number>();
    for (const f of r.facts) if (f.doc_no !== undefined) by.set(f.doc_no, (by.get(f.doc_no) ?? 0) + 1);
    return { by, total: r.facts.length };
  }, [runPath, done], done && !!runPath);
  if (!bid || !job) {
    return <section className="in-card"><p className="in-lede" style={{ margin: 0 }}>The extraction has not been started. Start it from the review step.</p></section>;
  }

  const steps = job.steps ?? [];
  const byNo = new Map(bid.documents.map((d) => [d.no, d]));
  const jobDocs = flow.jobDocs.length ? flow.jobDocs : [...new Set(steps.filter((s) => s.doc_no > 0).map((s) => s.doc_no))];
  const docs: BidDocument[] = rowsInOrder(bid).filter((d) => jobDocs.includes(d.no));
  const files = new Map(bid.documents.map((d) => [d.no, d.file_name]));
  const pct = Math.round(jobProgress(steps, docs.map((d) => d.no)) * 100);
  const counts = facts.data;
  const summary = flow.bids?.find((b) => b.bid_id === bid.bid_id);
  const total = counts?.total ?? summary?.facts ?? null;
  const bidSteps = latest(steps.filter((s) => s.doc_no === 0 && BID_STEPS.includes(s.step)));
  const failedDocs = docs.filter((d) => d.status === 'failed' || docRunState(steps, d.no) === 'failed');

  if (job.status === 'failed') {
    return (
      <section className="in-card" role="alert">
        <InlineAlert variant="negative">
          <Heading>The extraction failed</Heading>
          <Content><span className="in-text">{job.error}</span></Content>
        </InlineAlert>
        {failedDocs.length > 0 && (
          <ul className="in-list" style={{ marginTop: 12 }}>
            {failedDocs.map((d) => <li key={d.no} className="in-text">d{d.no} {d.file_name}{d.error ? `: ${d.error}` : ''}</li>)}
          </ul>
        )}
        <Flex gap="size-150" marginTop="size-200">
          <Button variant="accent" onPress={() => flow.setStep('review')}>Back to review</Button>
        </Flex>
      </section>
    );
  }

  if (done) {
    return (
      <>
        <section className="in-card">
          <IllustratedMessage>
            <CheckmarkCircle size="XXL" color="positive" />
            <Heading>The fact list is ready</Heading>
            <Content>{job.result}.{job.seconds >= 1 ? ` Took ${clock(job.seconds)}.` : ''}</Content>
          </IllustratedMessage>
          <div className="in-stats" style={{ marginTop: 24 }}>
            <div className="in-stat"><div className="in-v">{total ?? '-'}</div><div className="in-l">facts</div></div>
            <div className="in-stat"><div className="in-v">{docs.length - failedDocs.length}</div><div className="in-l">{docs.length - failedDocs.length === 1 ? 'document read' : 'documents read'}</div></div>
          </div>
          {failedDocs.length > 0 && (
            <InlineAlert variant="negative" marginTop="size-200">
              <Heading>{failedDocs.length === 1 ? 'One document failed' : `${failedDocs.length} documents failed`}</Heading>
              <Content>The others were read. Start the extraction again from the review step to try the failed ones once more.</Content>
            </InlineAlert>
          )}
          <Flex gap="size-150" justifyContent="center" marginTop="size-300" wrap>
            <Button variant="secondary" style="outline" onPress={flow.closeBid}>Back to bids</Button>
            {failedDocs.length > 0 && <Button variant="secondary" onPress={() => flow.setStep('review')}>Back to review</Button>}
            {runPath && <Button variant="accent" onPress={() => flow.openFacts(runPath)}>Open the fact list</Button>}
          </Flex>
        </section>
        <section className="in-card">
          <h2>By document</h2>
          {docs.map((d) => {
            const bad = failedDocs.includes(d);
            return (
              <Flex key={d.no} alignItems="center" gap="size-150" UNSAFE_style={{ padding: '8px 0', borderBottom: '1px solid var(--spectrum-global-color-gray-200)' }}>
                <FileBadge name={d.file_name} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <strong className="in-text">{d.file_name}</strong>
                  {bad && d.error && <div className="in-bad in-small">{d.error}</div>}
                </div>
                <span>{bad ? 'Failed' : byNo.has(d.no) && counts ? `${counts.by.get(d.no) ?? 0} facts` : ''}</span>
              </Flex>
            );
          })}
        </section>
      </>
    );
  }

  return (
    <>
      <section className="in-card" aria-live="polite">
        <Flex alignItems="end" gap="size-200" wrap>
          <div style={{ flex: 1 }}>
            <h2>Reading the bid</h2>
            <p className="in-lede" style={{ margin: 0 }}>{runningNow(steps, files) || 'Starting'}</p>
          </div>
          <div className="in-muted in-small" style={{ textAlign: 'right' }}>Elapsed {clock(job.seconds)}</div>
        </Flex>
        <ProgressBar label="Overall" value={pct} width="100%" marginTop="size-200" />
        <p className="in-muted in-small" style={{ marginBottom: 0 }}>You can leave this page. The extraction goes on, and the bid shows as reading in the list.</p>
      </section>
      <section className="in-card" aria-label="Progress by document">
        {docs.map((d) => {
          const state = docRunState(steps, d.no);
          const own = latest(steps.filter((s) => s.doc_no === d.no));
          return (
            <div className="in-docrun" key={d.no}>
              <Disclosure isQuiet defaultExpanded={state === 'running' || state === 'failed'}>
                <DisclosureTitle>
                  <Flex alignItems="center" gap="size-150" width="100%">
                    <FileBadge name={d.file_name} />
                    <span className="in-text" style={{ fontWeight: 600 }}>{d.file_name}</span>
                    <div style={{ flex: 1 }} />
                    <Light state={state} />
                  </Flex>
                </DisclosureTitle>
                <DisclosurePanel>
                  <div className="in-tasks">{own.length ? own.map((s) => <TaskLine key={s.step} s={s} />) : <span className="in-muted in-small">Waiting for its turn.</span>}</div>
                </DisclosurePanel>
              </Disclosure>
            </div>
          );
        })}
        <div className="in-docrun">
          <strong>The whole bid</strong>
          <div className="in-tasks">{bidSteps.length ? bidSteps.map((s) => <TaskLine key={s.step} s={s} />) : <span className="in-muted in-small">Starts when the documents are read.</span>}</div>
        </div>
      </section>
    </>
  );
}
