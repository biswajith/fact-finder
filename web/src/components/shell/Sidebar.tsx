import { useEffect, useState, type ReactNode } from 'react';
import { useRun } from '../../store';
import { hashForPage, type PageName } from '../../nav';
import { formatTime } from '../common';
import { activeChanges } from '../ChangesTab';
import type { BidFlow } from '../../bidFlow';

interface Item { page: PageName; label: string; pill?: ReactNode }

const documentsWord = (n: number) => `${n} ${n === 1 ? 'document' : 'documents'}`;

function RunSelect({ flow }: { flow: BidFlow }) {
  const { runs, run, selectRun, runInfo, facts, liveFacts, page, goTo } = useRun();
  // The open run counts its live facts (with the reader's adds and deletes); others their stored count.
  const count = (r: { run: string; facts: number }) => (r.run === run && facts.data ? liveFacts.length : r.facts);
  const bids = flow.bids ?? [];
  // A bid with no facts has no run: choosing it opens its Documents page, and the selector shows it there.
  const pending = page === 'documents' ? bids.find((b) => b.bid_id === flow.bidId && !b.run) : undefined;
  const meta = pending
    ? documentsWord(pending.documents)
    : [runInfo ? formatTime(runInfo.modified) : '', runInfo ? `${count(runInfo)} facts` : ''].filter(Boolean).join(' · ');
  const title = pending ? pending.name : runInfo?.kind === 'bid' && runInfo.name ? runInfo.name : (runInfo?.doc_id ?? run);
  const onChange = (value: string) => {
    if (value.startsWith('bid:')) {
      flow.selectBid(value.slice(4));
      goTo('documents');
      return;
    }
    selectRun(value);
  };
  const bidRuns = new Set(bids.filter((b) => b.run).map((b) => b.run));
  return (
    <label className="run-select">
      <span className="doc">{title}</span>
      <span className="meta">{meta}</span>
      <span className="caret" aria-hidden>▾</span>
      <select aria-label="Run" value={pending ? `bid:${pending.bid_id}` : run} onChange={(e) => onChange(e.target.value)}>
        {bids.map((b) => (
          <option key={`bid:${b.bid_id}`} value={b.run || `bid:${b.bid_id}`}>
            {b.run ? `${b.name} · ${documentsWord(b.documents)}` : `${b.name} · no facts yet`}
          </option>
        ))}
        {runs.filter((r) => r.kind !== 'bid' && !bidRuns.has(r.run)).map((r) => (
          <option key={r.run} value={r.run}>{`${r.doc_id} · ${r.run_id} (${count(r)} facts)`}</option>
        ))}
      </select>
    </label>
  );
}

export function Sidebar({ open, onNavigate, flow }: { open: boolean; onNavigate: () => void; flow: BidFlow }) {
  const { page, conflicts, corrections, status } = useRun();
  const openConflicts = (conflicts.data ?? []).filter((c) => c.status === 'open').length;
  const changes = activeChanges(corrections.data ?? []).length;
  const running = flow.running ? <span className="pill info">running</span> : null;
  const review: Item[] = [
    { page: 'documents', label: 'Documents', pill: running },
    { page: 'overview', label: 'Overview' },
    { page: 'facts', label: 'Facts' },
    { page: 'conflicts', label: 'Conflicts', pill: <span className={`pill${openConflicts ? ' warn' : ''}`} aria-label={`${openConflicts} open`}>{openConflicts}</span> },
    { page: 'changes', label: 'Changes', pill: changes ? <span className="pill">{changes}</span> : null },
  ];
  // Pages for whoever runs the extractor, folded away from the bid manager's pages.
  const developer: Item[] = [
    { page: 'report', label: 'Report' },
    { page: 'compare', label: 'Compare' },
    { page: 'chatlog', label: 'Chat log' },
  ];
  const onDevPage = developer.some((it) => it.page === page);
  const [devOpen, setDevOpen] = useState(onDevPage);
  useEffect(() => {
    if (onDevPage) setDevOpen(true);
  }, [onDevPage]);
  const link = (it: Item) => (
    <a key={it.page} className="nav-item" href={hashForPage(it.page)} aria-current={page === it.page ? 'page' : undefined} onClick={onNavigate}>
      <span className="grow">{it.label}</span>
      {it.pill}
    </a>
  );
  return (
    <aside className={`sidebar${open ? ' open' : ''}`} id="app-sidebar" aria-label="Sidebar">
      <div className="brand">RFP facts</div>
      <RunSelect flow={flow} />
      <button
        type="button"
        className="new-bid-btn"
        onClick={() => {
          flow.startNew();
          window.location.hash = hashForPage('documents');
          onNavigate();
        }}
      >
        + New bid
      </button>
      <nav aria-label="Pages">
        <div className="nav" role="group" aria-label="Review">
          <div className="nav-group">Review</div>
          {review.map(link)}
        </div>
        <details className="nav nav-dev" open={devOpen} onToggle={(e) => setDevOpen(e.currentTarget.open)}>
          <summary className="nav-group">
            <span className="grow">Developer</span>
                </summary>
          {developer.map(link)}
        </details>
      </nav>
      <div className="sidebar-foot">
        {status && !status.has_key && <div className="no-key" role="status">No API key: chat and summaries are off</div>}
      </div>
    </aside>
  );
}
