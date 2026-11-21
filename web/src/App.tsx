import { useCallback, useEffect, useState } from 'react';
import {
  Badge, Button, Content, defaultTheme, Heading, InlineAlert, Item, Picker, Provider, TabList, TabPanels, Tabs,
  ToastContainer,
} from '@adobe/react-spectrum';
import * as api from './api';
import { ChangesTab } from './components/ChangesTab';
import { ChatPanel } from './components/ChatPanel';
import { CompareTab } from './components/CompareTab';
import { ConflictsTab } from './components/ConflictsTab';
import { Empty, ErrorBox, Loading } from './components/common';
import { FactDetail } from './components/FactDetail';
import { FactsTab } from './components/FactsTab';
import { NewRunTab } from './components/NewRunTab';
import { PdfControl } from './components/PdfControl';
import { ReportTab } from './components/ReportTab';
import { SummaryTab } from './components/SummaryTab';
import { useNewRun } from './newRun';
import { errorText, RunProvider, useRun } from './store';
import type { RunInfo, Status } from './types';

function readRunParam(): string | null {
  return new URLSearchParams(window.location.search).get('run');
}
function writeRunParam(run: string) {
  const u = new URL(window.location.href);
  u.searchParams.set('run', run);
  window.history.replaceState(null, '', u);
}

function Header({ runs, run, onRun, status, onToggleChat, chatOpen }: {
  runs: RunInfo[]; run: string; onRun: (r: string) => void; status: Status | null; onToggleChat: () => void; chatOpen: boolean;
}) {
  const { conflicts, corrections } = useRun();
  const openConflicts = (conflicts.data ?? []).filter((c) => c.status === 'open').length;
  const changes = (corrections.data ?? []).filter((c) => !c.undone && c.op !== 'undo' && c.op !== 'raise').length;
  return (
    <header className="app-header">
      <h1>RFP facts</h1>
      <Picker
        label="Run"
        labelPosition="side"
        selectedKey={run}
        onSelectionChange={(k) => onRun(String(k))}
        items={runs}
      >
        {(r) => <Item key={r.run}>{`${r.doc_id} · ${r.run_id} (${r.facts} facts)`}</Item>}
      </Picker>
      <PdfControl />
      <div className="header-counts" aria-label="Counts">
        <Badge variant={openConflicts ? 'yellow' : 'neutral'}>{openConflicts} open {openConflicts === 1 ? 'conflict' : 'conflicts'}</Badge>
        <Badge variant={changes ? 'info' : 'neutral'}>{changes} {changes === 1 ? 'change' : 'changes'}</Badge>
      </div>
      {status && !status.has_key && <Badge variant="negative">No API key: chat and summaries are off</Badge>}
      <span className="header-spacer" />
      <span className="chat-toggle">
        <Button variant="secondary" onPress={onToggleChat} aria-expanded={chatOpen}>{chatOpen ? 'Hide chat' : 'Show chat'}</Button>
      </span>
    </header>
  );
}

function Workspace({ runs, run, onRun, status }: { runs: RunInfo[]; run: string; onRun: (r: string) => void; status: Status | null }) {
  const [chatOpen, setChatOpen] = useState(false);
  const { conflicts } = useRun();
  const openCount = (conflicts.data ?? []).filter((c) => c.status === 'open').length;
  const { refreshRuns, selectRun } = useRun();
  const newRun = useNewRun(status, refreshRuns, selectRun);
  return (
    <div className="app">
      <Header runs={runs} run={run} onRun={onRun} status={status} onToggleChat={() => setChatOpen((v) => !v)} chatOpen={chatOpen} />
      <div className={`layout${chatOpen ? ' chat-open' : ''}`}>
        <main className="main-area">
          <Tabs aria-label="Views">
            <TabList>
              <Item key="summary">Summary</Item>
              <Item key="facts">Facts</Item>
              <Item key="conflicts">{openCount ? `Conflicts (${openCount})` : 'Conflicts'}</Item>
              <Item key="changes">Changes</Item>
              <Item key="report">Run report</Item>
              <Item key="compare">Compare</Item>
              <Item key="new">{newRun.running ? 'New run (running)' : 'New run'}</Item>
            </TabList>
            <TabPanels>
              <Item key="summary"><SummaryTab /></Item>
              <Item key="facts"><FactsTab /></Item>
              <Item key="conflicts"><ConflictsTab /></Item>
              <Item key="changes"><ChangesTab /></Item>
              <Item key="report"><ReportTab /></Item>
              <Item key="compare"><CompareTab /></Item>
              <Item key="new"><NewRunTab n={newRun} /></Item>
            </TabPanels>
          </Tabs>
        </main>
        <ChatPanel onClose={() => setChatOpen(false)} />
      </div>
      <FactDetail />
    </div>
  );
}

function Shell() {
  const [status, setStatus] = useState<Status | null>(null);
  const [runs, setRuns] = useState<RunInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [run, setRunState] = useState<string | null>(readRunParam());

  const load = useCallback(async () => {
    setError(null);
    setRuns(null);
    try {
      const [s, r] = await Promise.all([api.getStatus(), api.getRuns()]);
      setStatus(s);
      setRuns(r);
      setRunState((cur) => (cur && r.some((x) => x.run === cur) ? cur : (r[0]?.run ?? null)));
    } catch (e) {
      setError(errorText(e));
    }
  }, []);
  useEffect(() => void load(), [load]);
  const refreshRuns = useCallback(async () => {
    const r = await api.getRuns();
    setRuns(r);
    return r;
  }, []);

  useEffect(() => {
    if (run) writeRunParam(run);
  }, [run]);

  if (error) {
    return (
      <div style={{ padding: 24, maxWidth: 640 }}>
        <ErrorBox message={error} onRetry={() => void load()} />
      </div>
    );
  }
  if (!runs) return <Loading label="Loading runs" />;
  if (!run) {
    return (
      <div style={{ padding: 24, maxWidth: 640 }}>
        <InlineAlert variant="info">
          <Heading>No runs found</Heading>
          <Content>
            <Empty>Nothing to show yet. Extract an RFP first, or start the server with --runs pointing at a folder of runs
              {status ? ` (now: ${status.runs_folder})` : ''}.</Empty>
            <Button variant="secondary" onPress={() => void load()}>Check again</Button>
          </Content>
        </InlineAlert>
      </div>
    );
  }
  return (
    <RunProvider run={run} runs={runs} refreshRuns={refreshRuns} selectRun={setRunState} status={status}>
      <Workspace runs={runs} run={run} onRun={setRunState} status={status} />
    </RunProvider>
  );
}

export default function App() {
  return (
    <Provider theme={defaultTheme} height="100%">
      <ToastContainer />
      <Shell />
    </Provider>
  );
}
