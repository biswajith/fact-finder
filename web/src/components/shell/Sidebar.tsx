import { useEffect, useState, type ReactNode } from 'react';
import { useRun } from '../../store';
import { hashForPage, type PageName } from '../../nav';
import { useTheme, type ThemeMode } from '../../theme';
import { formatTime } from '../common';
import { activeChanges } from '../ChangesTab';

interface Item { page: PageName; label: string; pill?: ReactNode }

function RunSelect() {
  const { runs, run, selectRun, runInfo, facts, liveFacts } = useRun();
  // The open run counts its live facts (with the reader's adds and deletes); others their stored count.
  const count = (r: { run: string; facts: number }) => (r.run === run && facts.data ? liveFacts.length : r.facts);
  const meta = [runInfo ? formatTime(runInfo.modified) : '', runInfo ? `${count(runInfo)} facts` : ''].filter(Boolean).join(' · ');
  return (
    <label className="run-select">
      <span className="doc">{runInfo?.doc_id ?? run}</span>
      <span className="meta">{meta}</span>
      <span className="caret" aria-hidden>▾</span>
      <select aria-label="Run" value={run} onChange={(e) => selectRun(e.target.value)}>
        {runs.map((r) => <option key={r.run} value={r.run}>{`${r.doc_id} · ${r.run_id} (${count(r)} facts)`}</option>)}
      </select>
    </label>
  );
}

const MODES: { mode: ThemeMode; label: string }[] = [
  { mode: 'system', label: 'System' }, { mode: 'light', label: 'Light' }, { mode: 'dark', label: 'Dark' },
];

function ThemeSwitch() {
  const { mode, setMode } = useTheme();
  return (
    <div className="theme-switch" role="group" aria-label="Theme">
      {MODES.map((m) => (
        <button key={m.mode} type="button" aria-pressed={mode === m.mode} onClick={() => setMode(m.mode)}>{m.label}</button>
      ))}
    </div>
  );
}

export function Sidebar({ open, onNavigate, newRunning }: { open: boolean; onNavigate: () => void; newRunning: boolean }) {
  const { page, conflicts, corrections, status } = useRun();
  const openConflicts = (conflicts.data ?? []).filter((c) => c.status === 'open').length;
  const changes = activeChanges(corrections.data ?? []).length;
  const running = newRunning ? <span className="pill info">running</span> : null;
  const review: Item[] = [
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
    { page: 'new', label: 'New run', pill: running },
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
      <RunSelect />
      <nav aria-label="Pages">
        <div className="nav" role="group" aria-label="Review">
          <div className="nav-group">Review</div>
          {review.map(link)}
        </div>
        <details className="nav nav-dev" open={devOpen} onToggle={(e) => setDevOpen(e.currentTarget.open)}>
          <summary className="nav-group">
            <span className="grow">Developer</span>
            {!devOpen && running}
          </summary>
          {developer.map(link)}
        </details>
      </nav>
      <div className="sidebar-foot">
        {status && !status.has_key && <div className="no-key" role="status">No API key: chat and summaries are off</div>}
        <ThemeSwitch />
      </div>
    </aside>
  );
}
