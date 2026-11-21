import type { ReactNode } from 'react';
import { useRun } from '../../store';
import { hashForPage, type PageName } from '../../nav';
import { useTheme, type ThemeMode } from '../../theme';
import { formatTime } from '../common';
import { PdfControl } from '../PdfControl';

interface Item { page: PageName; label: string; pill?: ReactNode }

function RunSelect() {
  const { runs, run, selectRun, runInfo } = useRun();
  const meta = [runInfo ? formatTime(runInfo.modified) : '', runInfo ? `${runInfo.facts} facts` : ''].filter(Boolean).join(' · ');
  return (
    <label className="run-select">
      <span className="doc">{runInfo?.doc_id ?? run}</span>
      <span className="meta">{meta}</span>
      <span className="caret" aria-hidden>▾</span>
      <select aria-label="Run" value={run} onChange={(e) => selectRun(e.target.value)}>
        {runs.map((r) => <option key={r.run} value={r.run}>{`${r.doc_id} · ${r.run_id} (${r.facts} facts)`}</option>)}
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
  const changes = (corrections.data ?? []).filter((c) => !c.undone && c.op !== 'undo' && c.op !== 'raise').length;
  const groups: { name: string; items: Item[] }[] = [
    { name: 'Review', items: [
      { page: 'overview', label: 'Overview' },
      { page: 'facts', label: 'Facts' },
      { page: 'conflicts', label: 'Conflicts', pill: <span className={`pill${openConflicts ? ' warn' : ''}`} aria-label={`${openConflicts} open`}>{openConflicts}</span> },
      { page: 'changes', label: 'Changes', pill: changes ? <span className="pill">{changes}</span> : null },
    ] },
    { name: 'Run', items: [
      { page: 'report', label: 'Report' },
      { page: 'compare', label: 'Compare' },
      { page: 'chatlog', label: 'Chat log' },
      { page: 'new', label: 'New run', pill: newRunning ? <span className="pill info">running</span> : null },
    ] },
  ];
  return (
    <aside className={`sidebar${open ? ' open' : ''}`} id="app-sidebar" aria-label="Sidebar">
      <h1 className="brand">RFP facts</h1>
      <RunSelect />
      <nav aria-label="Pages">
        {groups.map((g) => (
          <div className="nav" key={g.name} role="group" aria-label={g.name}>
            <div className="nav-group">{g.name}</div>
            {g.items.map((it) => (
              <a key={it.page} className="nav-item" href={hashForPage(it.page)} aria-current={page === it.page ? 'page' : undefined} onClick={onNavigate}>
                <span className="grow">{it.label}</span>
                {it.pill}
              </a>
            ))}
          </div>
        ))}
      </nav>
      <div className="sidebar-foot">
        <PdfControl />
        {status && !status.has_key && <div className="no-key" role="status">No API key: chat and summaries are off</div>}
        <ThemeSwitch />
      </div>
    </aside>
  );
}
