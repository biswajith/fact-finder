import { useEffect, useMemo, useState } from 'react';
import * as api from '../api';
import { useAsync } from '../hooks';
import { useRun } from '../store';
import type { Report } from '../types';
import { Empty, ErrorBox, Loading } from './common';
import { PageHeader } from './shell/PageHeader';
import './pages.css';

const fmtNum = (v: unknown) => (typeof v === 'number' ? v.toLocaleString() : '-');

export function Stat({ label, value, hint, tone = '' }: { label: string; value: string | number; hint?: string; tone?: string }) {
  return (
    <div role="listitem" className={`stat ${tone}`}>
      <div className="l">{label}</div>
      <div className="v">{value}</div>
      {hint !== undefined && <div className="h">{hint}</div>}
    </div>
  );
}

function ReportBody({ rep, run }: { rep: Report; run: string }) {
  const calls = rep.calls ?? [];
  const secs = rep.seconds ?? {};
  const failed = rep.failed_calls ?? [];
  const incomplete = rep.incomplete_calls ?? [];
  const byStatus = new Map<string, number>();
  for (const c of calls) byStatus.set(String(c.status), (byStatus.get(String(c.status)) ?? 0) + 1);
  const hit = rep.cache_hit_calls_2_to_n;
  const [sel, setSel] = useState<number | null>(null);
  useEffect(() => setSel(null), [run]);
  const call = sel !== null ? calls[sel] : undefined;
  const stages = useMemo(() => Object.entries(secs).filter(([k]) => k !== 'total').map(([k, v]) => `${k} ${v} s`).join(', '), [secs]);
  return (
    <>
      <div className="rp-stats" role="list" aria-label="Run totals">
        <Stat label="Total time" value={`${secs.total ?? '-'} s`} hint={stages} />
        <Stat label="Output tokens" value={fmtNum(rep.output_tokens)} hint="reasoning included" />
        <Stat label="Cache hit" value={typeof hit === 'number' ? `${Math.round(hit * 100)}%` : '-'} hint="input tokens of calls 2..n" />
        <Stat label="Calls" value={calls.length} hint={[...byStatus].map(([k, n]) => `${n} ${k}`).join(', ')} />
        <Stat label="Failed calls" value={failed.length} hint={failed.map(String).join(', ') || 'none'} tone={failed.length ? 'bad' : ''} />
        <Stat label="Incomplete calls" value={incomplete.length} hint={incomplete.map(String).join(', ') || 'none'} tone={incomplete.length ? 'warn' : ''} />
      </div>
      {(incomplete.length > 0 || !!rep.units_unanswered_votes) && (
        <div className="pg-note">
          {rep.units_unanswered_votes ?? 0} label votes are missing: a call that answers for only some of its units is asked once more,
          and is listed as incomplete if it is still short. Those units were decided on fewer votes.
        </div>
      )}
      <h2 className="pg-h2">Calls</h2>
      {calls.length === 0 ? (
        <Empty>This report lists no calls.</Empty>
      ) : (
        <div className="pg-table-wrap">
          <table className="data-table" aria-label="Calls">
            <thead>
              <tr>
                <th scope="col">Name</th><th scope="col">Kind</th><th scope="col">Status</th>
                <th scope="col" className="num">Seconds</th><th scope="col" className="num">Lines</th>
                <th scope="col" className="num">Output tokens</th><th scope="col" className="num">Retries</th>
              </tr>
            </thead>
            <tbody>
              {calls.map((c, i) => (
                <tr key={i} className={i === sel ? 'sel' : undefined}>
                  <td>
                    <button type="button" className="linkbtn" aria-pressed={i === sel} aria-label={`Show the log and output of call ${c.name ?? i + 1}`} onClick={() => setSel(i === sel ? null : i)}>
                      {c.name ?? `#${i + 1}`}
                    </button>
                  </td>
                  <td>{c.kind ?? ''}</td>
                  <td>{c.status ?? ''}</td>
                  <td className="num">{typeof c.seconds === 'number' ? c.seconds.toFixed(2) : ''}</td>
                  <td className="num">{c.lines ?? ''}</td>
                  <td className="num">{c.usage?.output_tokens ?? ''}</td>
                  <td className="num">{c.retries ?? ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {!call ? (
        <div className="pg-note">Select a call to see its log and output.</div>
      ) : (
        <>
          <details className="pg-fold" key={`log-${sel}`}>
            <summary>Log of {call.name ?? 'this call'}</summary>
            <pre className="pg-code" aria-label={`Log of call ${call.name ?? ''}`}>{(call.log ?? []).map(String).join('\n') || '(empty)'}</pre>
          </details>
          <details className="pg-fold" key={`out-${sel}`}>
            <summary>Output of {call.name ?? 'this call'}</summary>
            <pre className="pg-code" aria-label={`Output of call ${call.name ?? ''}`}>{call.output || '(empty)'}</pre>
          </details>
        </>
      )}
    </>
  );
}

function AllRuns() {
  const { runs } = useRun();
  // Reload when the run list changes (a run finished).
  const t = useAsync((signal) => api.getRunsTable(signal), [runs]);
  return (
    <>
      <h2 className="pg-h2">All runs in this folder</h2>
      <div className="pg-note">
        Wall-clock seconds from the run report. Extract is the first round of calls; sweep and check is everything after it.
        A run with no report shows no timing.
      </div>
      {t.loading && !t.data ? <Loading label="Loading runs" /> : t.error && !t.data ? <ErrorBox message={t.error} onRetry={t.reload} /> : (
        <div className="pg-table-wrap">
          <table className="data-table" aria-label="All runs">
            <thead>
              <tr>
                <th scope="col">Run</th><th scope="col">Document</th><th scope="col" className="num">Facts</th>
                <th scope="col" className="num">Total (s)</th><th scope="col" className="num">Extract (s)</th>
                <th scope="col" className="num">Sweep and check (s)</th><th scope="col" className="num">Output tokens</th><th scope="col">Finished</th>
              </tr>
            </thead>
            <tbody>
              {(t.data ?? []).map((r) => (
                <tr key={r.run}>
                  <td>{r.run}</td><td>{r.document}</td><td className="num">{r.facts}</td>
                  <td className="num">{r['total s']?.toFixed(1) ?? ''}</td>
                  <td className="num">{r['extract s']?.toFixed(1) ?? ''}</td>
                  <td className="num">{r['sweep and check s']?.toFixed(1) ?? ''}</td>
                  <td className="num">{fmtNum(r['output tokens']).replace('-', '')}</td>
                  <td>{r.finished}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

export function ReportTab() {
  const { run } = useRun();
  const rep = useAsync((signal) => api.getReport(run, signal), [run]);
  return (
    <>
      <PageHeader title="Run report" subtitle={run} />
      <div className="pg-stack">
      {rep.loading && !rep.data ? (
        <Loading label="Loading the report" />
      ) : rep.status === 404 ? (
        <Empty>This run has no report.</Empty>
      ) : rep.error ? (
        <ErrorBox message={rep.error} onRetry={rep.reload} />
      ) : rep.data ? (
        <ReportBody rep={rep.data} run={run} />
      ) : null}
      <AllRuns />
      </div>
    </>
  );
}
