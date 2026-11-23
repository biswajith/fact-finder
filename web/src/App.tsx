import { useCallback, useEffect, useState } from 'react';
import { Button, defaultTheme, Provider, ToastContainer } from '@adobe/react-spectrum';
import * as api from './api';
import { ErrorBox, Loading } from './components/common';
import { NewRunTab } from './components/NewRunTab';
import { Workspace } from './components/shell/Workspace';
import { useNewRun } from './newRun';
import { errorText, RunProvider } from './store';
import { ThemeProvider, useTheme } from './theme';
import type { RunInfo, Status } from './types';

function readRunParam(): string | null {
  return new URLSearchParams(window.location.search).get('run');
}
function writeRunParam(run: string) {
  const u = new URL(window.location.href);
  u.searchParams.set('run', run);
  window.history.replaceState(null, '', u);
}

/** With no runs yet, the app is the New run page. A finished run becomes the open run. */
function NoRuns({ status, refreshRuns, selectRun, recheck }: {
  status: Status | null; refreshRuns: () => Promise<RunInfo[]>; selectRun: (run: string) => void; recheck: () => void;
}) {
  const n = useNewRun(status, refreshRuns, (r) => { window.location.hash = '#/overview'; selectRun(r); });
  return (
    <main className="page">
      <div className="pg-note">
        No runs yet{status ? ` in ${status.runs_folder}` : ''}. Extract one below, or start the server with --runs
        pointing at a folder of runs. <Button variant="secondary" onPress={recheck}>Check again</Button>
      </div>
      <NewRunTab n={n} status={status} />
    </main>
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
  if (!run) return <NoRuns status={status} refreshRuns={refreshRuns} selectRun={setRunState} recheck={() => void load()} />;
  return (
    <RunProvider run={run} runs={runs} refreshRuns={refreshRuns} selectRun={setRunState} status={status}>
      <Workspace />
    </RunProvider>
  );
}

function Themed() {
  const { resolved } = useTheme();
  return (
    <Provider theme={defaultTheme} colorScheme={resolved} height="100%" UNSAFE_style={{ background: 'var(--bg)', color: 'var(--text)' }}>
      <ToastContainer />
      <Shell />
    </Provider>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <Themed />
    </ThemeProvider>
  );
}
