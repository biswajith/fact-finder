import { Button, Checkbox } from '@adobe/react-spectrum';
import { extractCount, missingWords, rowsInOrder, stepsByDocument } from '../../bid';
import type { BidFlow } from '../../bidFlow';
import type { Bid, JobStep, Status } from '../../types';
import { ErrorBox } from '../common';

const STEP_NAMES: Record<string, string> = {
  cut: 'Cut into units', extract: 'Label the units and build facts', relate: 'Link to earlier documents', save: 'Save the result',
  group: 'Group repeated points', pairs: 'Check facts that disagree', build: 'Build the fact list',
};

function Check() {
  return (
    <svg className="pg-check" width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
      <path d="M2.5 7.5l3 3 6-7" />
    </svg>
  );
}

function StepMark({ s }: { s: JobStep }) {
  if (s.status === 'running') return <span className="pg-mark" role="img" aria-label="running"><span className="pg-pulse small" /></span>;
  if (s.status === 'failed') return <span className="pg-mark bad" role="img" aria-label="failed">✗</span>;
  return <span className="pg-mark" role="img" aria-label={s.status === 'reused' ? 'reused' : 'done'}><Check /></span>;
}

function clock(seconds: number): string {
  const t = Math.max(0, Math.round(seconds));
  return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, '0')}`;
}

/** The running job as a checklist: a finished document folds to one line, the running one lists its steps. */
function Progress({ steps, bid, running, seconds }: { steps: JobStep[]; bid: Bid; running: boolean; seconds: number | null }) {
  const groups = stepsByDocument(steps, rowsInOrder(bid));
  if (!running && !groups.length) return null;
  const now = groups.flatMap((g) => g.steps.filter((s) => s.status === 'running').map((s) => `${STEP_NAMES[s.step] ?? s.step}, ${g.title}`));
  return (
    <div className="pg-live">
      {running && (
        <div className="pg-live-head">
          <span className="pg-pulse" aria-hidden="true" />
          <strong>Extracting</strong>
          <span className="muted">This takes a few minutes.</span>
          {seconds !== null && <span className="pg-live-time muted" aria-label={`${Math.round(seconds)} seconds so far`}>{clock(seconds)}</span>}
          <span className="sr-only" role="status" aria-live="polite">{now.length ? `Running: ${now.join('; ')}` : 'Extracting'}</span>
        </div>
      )}
      {groups.map((g) => {
        const finished = g.steps.every((s) => s.status === 'done' || s.status === 'reused');
        const reused = finished && g.steps.every((s) => s.status === 'reused');
        return (
          <div key={g.no} className="pg-live-group">
            <div className="pg-live-title">
              {finished && <Check />}
              <strong className="wrap-text">{g.title}</strong>
              {finished && <span className="muted">{reused ? 'reused' : `${g.steps.length} ${g.steps.length === 1 ? 'step' : 'steps'}`}</span>}
            </div>
            {!finished && (
              <ul>
                {g.steps.map((s) => (
                  <li key={s.step} className={s.status}>
                    <StepMark s={s} />
                    <span>{STEP_NAMES[s.step] ?? s.step}{s.status === 'reused' ? ' (reused)' : ''}{s.status === 'running' ? '...' : ''}</span>
                    {s.status === 'failed' && s.detail && <span className="pg-bad wrap-text">{s.detail}</span>}
                  </li>
                ))}
              </ul>
            )}
          </div>
        );
      })}
    </div>
  );
}

export function PlanAndStart({ flow, bid, status }: { flow: BidFlow; bid: Bid; status: Status | null }) {
  const { plan, job } = flow;
  const n = extractCount(plan);
  const waiting = (plan?.documents ?? []).filter((d) => d.missing.length > 0);
  const rebuild = n === 0 && !!bid.run;
  const fileOf = (no: number) => bid.documents.find((d) => d.no === no)?.file_name ?? '';
  const done = job?.status === 'done' ? job : null;
  const failed = job?.status === 'failed' ? job : null;
  const canStart = flow.confirmed && !!status?.has_key && !!plan && waiting.length === 0 && (n > 0 || rebuild) && !flow.running;
  const label = rebuild ? 'Rebuild the fact list' : `Extract ${n} ${n === 1 ? 'document' : 'documents'}`;

  return (
    <div className="pg-stack">
      {done && (
        <div className="pg-banner ok" role="status">
          <strong>Extraction finished</strong>
          <div className="wrap-text">{done.result}</div>
        </div>
      )}
      {failed && (
        <div className="pg-banner bad" role="alert">
          <strong>The extraction failed</strong>
          <span className="wrap-text">{failed.error}</span>
        </div>
      )}
      {flow.planError ? (
        <ErrorBox message={`Could not plan the calls: ${flow.planError}`} onRetry={flow.replan} />
      ) : flow.planLoading && !plan ? (
        <div className="row" role="status"><span className="pg-pulse" aria-hidden="true" /> Reading the documents...</div>
      ) : plan ? (
        <>
          {plan.documents.map((d) => (
            <details className="pg-fold" key={d.no}>
              <summary>
                d{d.no} {d.file_name}: {d.total_calls} calls over {d.units} units{d.stored ? ', stored result found' : ''}
              </summary>
              {d.error ? (
                <div className="pg-note bad wrap-text">{d.error}</div>
              ) : (
                <div className="pg-table-wrap">
                  <table className="data-table" aria-label={`Planned calls for d${d.no}`}>
                    <thead><tr><th scope="col">Call</th><th scope="col" className="num">Times</th><th scope="col" className="num">Units</th><th scope="col">Pages</th></tr></thead>
                    <tbody>
                      {d.calls.map((r) => (
                        <tr key={r.call}><td>{r.call}</td><td className="num">{r.times}</td><td className="num">{r.units}</td><td>{r.pages}</td></tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {d.stored && (
                <div className="muted">A stored result is reused ({d.stored.facts} facts, {d.stored.created}).</div>
              )}
            </details>
          ))}
          {plan.skipped.length > 0 && (
            <div className="pg-note">
              Not read yet: {plan.skipped.map((s) => `d${s.no} ${fileOf(s.no)} (${s.why})`).join('; ')}.
            </div>
          )}
          {plan.relate_again.length > 0 && (
            <div className="pg-note">
              Links from {plan.relate_again.map((no) => `d${no}`).join(', ')} will be read again because an earlier document was added.
            </div>
          )}
          <div><strong>{plan.total_calls} calls in total</strong></div>
          {waiting.map((d) => <div key={d.no} className="pg-note">d{d.no}: {missingWords(d.missing)}</div>)}
        </>
      ) : bid.documents.length === 0 ? (
        <div className="pg-note">Add and confirm documents to see the planned calls.</div>
      ) : null}

      <div className="pg-confirm">
        <strong>This calls the model</strong>
        <div className="body">Reading the documents calls the model and spends API tokens.</div>
        <Checkbox isSelected={flow.confirmed} onChange={flow.setConfirmed}>I understand this spends API tokens</Checkbox>
      </div>
      {status && !status.has_key && (
        <div className="pg-banner bad" role="alert">
          <strong>No API key</strong>
          <span>The API key is not set (in the environment or .env), so no extraction can start.</span>
        </div>
      )}
      {flow.startError && <ErrorBox message={flow.startError} />}
      <div className="pg-actions">
        <Button variant="accent" isDisabled={!canStart} onPress={() => void flow.start()}>{label}</Button>
      </div>
      <Progress steps={job?.steps ?? []} bid={bid} running={flow.running} seconds={job ? job.seconds : null} />
    </div>
  );
}
