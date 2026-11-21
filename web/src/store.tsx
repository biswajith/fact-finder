import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { ToastQueue } from '@adobe/react-spectrum';
import * as api from './api';
import { hashForPage, pageFromHash, type PageName } from './nav';
import type { Conflict, CorrectionEntry, Fact, FactsListFilters, FactsResponse, RunInfo, Status, SummariesResponse } from './types';

export interface Resource<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
}
const empty = <T,>(): Resource<T> => ({ data: null, error: null, loading: true });

export function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

interface RunCtx {
  run: string;
  runs: RunInfo[];
  /** The current run's entry in `runs`. */
  runInfo: RunInfo | undefined;
  /** Reload the run list (after a new run, or a PDF attached or removed). */
  refreshRuns: () => Promise<RunInfo[]>;
  selectRun: (run: string) => void;
  status: Status | null;
  facts: Resource<FactsResponse>;
  conflicts: Resource<Conflict[]>;
  corrections: Resource<CorrectionEntry[]>;
  summaries: Resource<SummariesResponse>;
  factById: Map<string, Fact>;
  liveFacts: Fact[];
  reloadAll: () => Promise<void>;
  setSummaries: (s: SummariesResponse) => void;
  /** Run a write; on success reload everything and (optionally) toast, on failure toast the error. */
  act: <T>(fn: () => Promise<T>, doneMessage?: string) => Promise<T | undefined>;
  openFactId: string | null;
  openFact: (id: string | null) => void;
  chatDraft: string;
  setChatDraft: (s: string) => void;
  /** Goes up when the chat history was cleared elsewhere (a chat session deleted); the Assistant reloads. */
  chatEpoch: number;
  chatCleared: () => void;
  /** Navigation. The current page lives in the URL hash (#/overview ...); back and forward work. */
  page: PageName;
  goTo: (page: PageName) => void;
  /** Filters set by showFacts, waiting for the facts page to apply them; null when none. */
  factsPreset: Partial<FactsListFilters> | null;
  /** Set factsPreset and go to the facts page. */
  showFacts: (preset: Partial<FactsListFilters>) => void;
  /** Call once the facts page has applied the preset. */
  clearFactsPreset: () => void;
}

const Ctx = createContext<RunCtx | null>(null);
export function useRun(): RunCtx {
  const c = useContext(Ctx);
  if (!c) throw new Error('useRun outside RunProvider');
  return c;
}

export function RunProvider({ run, runs, refreshRuns, selectRun, status, children }: {
  run: string; runs: RunInfo[]; refreshRuns: () => Promise<RunInfo[]>; selectRun: (run: string) => void; status: Status | null; children: ReactNode;
}) {
  const [facts, setFacts] = useState<Resource<FactsResponse>>(empty);
  const [conflicts, setConflicts] = useState<Resource<Conflict[]>>(empty);
  const [corrections, setCorrections] = useState<Resource<CorrectionEntry[]>>(empty);
  const [summaries, setSummariesRes] = useState<Resource<SummariesResponse>>(empty);
  const [openFactId, openFact] = useState<string | null>(null);
  const [chatDraft, setChatDraft] = useState('');
  const [chatEpoch, setChatEpoch] = useState(0);
  const chatCleared = useCallback(() => setChatEpoch((n) => n + 1), []);
  const gen = useRef(0);
  const [page, setPage] = useState<PageName>(() => pageFromHash(window.location.hash));
  const [factsPreset, setFactsPreset] = useState<Partial<FactsListFilters> | null>(null);
  useEffect(() => {
    const on = () => setPage(pageFromHash(window.location.hash));
    window.addEventListener('hashchange', on);
    return () => window.removeEventListener('hashchange', on);
  }, []);
  const goTo = useCallback((p: PageName) => {
    if (pageFromHash(window.location.hash) === p && window.location.hash) return;
    window.location.hash = hashForPage(p);
  }, []);
  const showFacts = useCallback((preset: Partial<FactsListFilters>) => {
    setFactsPreset(preset);
    goTo('facts');
  }, [goTo]);
  const clearFactsPreset = useCallback(() => setFactsPreset(null), []);

  const load = useCallback(
    async <T,>(fn: () => Promise<T>, set: (f: (r: Resource<T>) => Resource<T>) => void, g: number) => {
      try {
        const data = await fn();
        if (g === gen.current) set(() => ({ data, error: null, loading: false }));
      } catch (e) {
        if (g === gen.current) set((r) => ({ data: r.data, error: errorText(e), loading: false }));
      }
    },
    [],
  );

  const reloadAll = useCallback(async () => {
    const g = gen.current;
    await Promise.all([
      load(() => api.getFacts(run, true), setFacts, g),
      load(() => api.getConflicts(run), setConflicts, g),
      load(() => api.getCorrections(run), setCorrections, g),
      load(() => api.getSummaries(run), setSummariesRes, g),
    ]);
  }, [run, load]);

  // New run: reset everything and load.
  useEffect(() => {
    gen.current += 1;
    setFacts(empty());
    setConflicts(empty());
    setCorrections(empty());
    setSummariesRes(empty());
    openFact(null);
    void reloadAll();
  }, [run, reloadAll]);

  // Poll the summaries every 2 seconds while the server is rebuilding any of them.
  const updating = summaries.data?.updating ?? false;
  useEffect(() => {
    if (!updating) return;
    const g = gen.current;
    const id = window.setInterval(() => void load(() => api.getSummaries(run), setSummariesRes, g), 2000);
    return () => window.clearInterval(id);
  }, [updating, run, load]);

  const setSummaries = useCallback(
    (s: SummariesResponse) => setSummariesRes({ data: s, error: null, loading: false }),
    [],
  );

  const act = useCallback(
    async <T,>(fn: () => Promise<T>, doneMessage?: string) => {
      try {
        const r = await fn();
        if (doneMessage) ToastQueue.positive(doneMessage, { timeout: 3000 });
        await reloadAll();
        return r;
      } catch (e) {
        ToastQueue.negative(errorText(e), { timeout: 8000 });
        return undefined;
      }
    },
    [reloadAll],
  );

  const factById = useMemo(() => new Map((facts.data?.facts ?? []).map((f) => [f.fact_id, f])), [facts.data]);
  const liveFacts = useMemo(() => (facts.data?.facts ?? []).filter((f) => !f.deleted), [facts.data]);

  const value: RunCtx = {
    run, runs, runInfo: runs.find((r) => r.run === run), refreshRuns, selectRun, status, facts, conflicts, corrections, summaries, factById, liveFacts, reloadAll, setSummaries, act,
    openFactId, openFact, chatDraft, setChatDraft, chatEpoch, chatCleared, page, goTo, factsPreset, showFacts, clearFactsPreset,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
