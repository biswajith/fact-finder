import { Button, Checkbox, ProgressCircle } from '@adobe/react-spectrum';
import { extractCount, missingWords, rowsInOrder, stepsByDocument } from '../../bid';
import type { BidFlow } from '../../bidFlow';
import type { Bid, JobStep, Status } from '../../types';
import { ErrorBox } from '../common';

const STEP_NAMES: Record<string, string> = {
  cut: 'Cut', extract: 'Extract', relate: 'Relate', save: 'Save', group: 'Group', pairs: 'Pairs', build: 'Build',
};

function StepMark({ s }: { s: JobStep }) {
  if (s.status === 'running') return <ProgressCircle aria-label={`${STEP_NAMES[s.step] ?? s.step} is running`} isIndeterminate size="S" />;
  if (s.status === 'failed') return <span className="pg-mark bad" role="img" aria-label="failed">✗</span>;
  return <span className="pg-mark ok" role="img" aria-label={s.status === 'reused' ? 'reused' : 'done'}>✓</span>;
}

function Steps({ steps, bid }: { steps: JobStep[]; bid: Bid }) {
  const groups = stepsByDocument(steps, rowsInOrder(bid));
  if (!groups.length) return null;
  return (
    <div className="pg-steps">
      {groups.map((g) => (
        <div key={g.no} className="pg-step-group">
          <strong className="wrap-text">{g.title}</strong>
          <ul>
            {g.steps.map((s) => (
              <li key={s.step}>
                <StepMark s={s} />
                <span>{STEP_NAMES[s.step] ?? s.step}{s.status === 'reused' ? ' (reused)' : ''}</span>
                {s.status === 'failed' && s.detail && <span className="pg-bad wrap-text">{s.detail}</span>}
              </li>
            ))}
          </ul>
        </div>
      ))}
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
    <section className="pg-stack" aria-labelledby="plan-title">
      <h2 className="pg-h2" id="plan-title">Read the documents</h2>
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
        <div className="row"><ProgressCircle aria-label="Planning the calls" isIndeterminate size="S" /> Reading the documents...</div>
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
        {flow.running && (
          <span className="pg-progress" role="status" aria-live="polite">
            <ProgressCircle aria-label="Extracting" isIndeterminate size="S" />
            Extracting... this takes a few minutes.{job ? ` ${Math.round(job.seconds)} s so far.` : ''}
          </span>
        )}
      </div>
      {job?.steps && job.steps.length > 0 && <Steps steps={job.steps} bid={bid} />}
    </section>
  );
}
