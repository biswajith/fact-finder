import { createContext, useContext, useEffect, useMemo, useReducer, type ReactNode } from 'react';
import { ToastQueue } from '@adobe/react-spectrum';
import { guess, issueOrder, newDoc, SAMPLES, type Doc, type DocType, type Person, type Side } from './data';

export type Step = 'details' | 'documents' | 'speakers' | 'review' | 'run';
export type View = 'bids' | 'intake';

export interface Details {
  name: string;
  customer: string;
  dealId: string;
  due: string | null;
  owner: string;
  team: Person[];
}

export interface Task {
  id: string;
  docId: string | null;
  label: string;
  total: number;
  left: number;
  status: 'waiting' | 'running' | 'done';
}

export interface Run {
  tasks: Task[];
  elapsed: number;
  done: boolean;
  facts: Record<string, number>;
}

export interface Mock {
  speed: number;
  failNext: boolean;
  modelOn: boolean;
}

interface State {
  view: View;
  step: Step;
  details: Details;
  docs: Doc[];
  /** Milliseconds left in each document's current phase. */
  left: Record<string, number>;
  votes: number;
  notify: boolean;
  run: Run | null;
  mock: Mock;
}

const EMPTY: Details = { name: '', customer: '', dealId: '', due: null, owner: 'Tom Okafor', team: [{ name: 'Tom Okafor', role: 'Bid manager' }] };

const initial = (mock?: Mock): State => ({
  view: 'bids', step: 'details', details: EMPTY, docs: [], left: {}, votes: 3, notify: true, run: null,
  mock: mock ?? { speed: 2, failNext: false, modelOn: true },
});

type Action =
  | { type: 'view'; view: View }
  | { type: 'step'; step: Step }
  | { type: 'details'; patch: Partial<Details> }
  | { type: 'add'; docs: Doc[]; fail: boolean }
  | { type: 'tick'; ms: number }
  | { type: 'patch'; id: string; patch: Partial<Doc> }
  | { type: 'confirm'; ids: string[] }
  | { type: 'remove'; ids: string[] }
  | { type: 'retry'; id: string }
  | { type: 'side'; docId: string; speakerId: string; side: Side; actsFor?: '' | 'buyer' | 'ours' }
  | { type: 'acceptSides'; docId: string }
  | { type: 'confirmSpeakers'; docId: string }
  | { type: 'votes'; votes: number }
  | { type: 'notify'; on: boolean }
  | { type: 'start' }
  | { type: 'mock'; patch: Partial<Mock> }
  | { type: 'reset' }
  | { type: 'sample'; docs: Doc[]; fail: boolean };

const PHASE_MS = { reading: 1400, classifying: 1600, speakers: 2200 } as const;

function startRun(s: State): Run {
  const tasks: Task[] = [];
  const docs = issueOrder(s.docs.filter((d) => d.confirmed));
  docs.forEach((d, i) => {
    const t = (label: string, ms: number) => tasks.push({ id: `${d.id}-${label}`, docId: d.id, label, total: ms, left: ms, status: 'waiting' });
    t('Read', 900 + d.pages * 25);
    t('Label units and build facts', 1500 + d.units * 6 * s.votes / 3);
    if (i > 0) t('Link to earlier documents', 1200 + d.units * 3);
    t('Save', 500);
  });
  for (const [label, ms] of [['Group repeated points', 2200], ['Check facts that disagree', 2600], ['Build the fact list', 900]] as const) {
    tasks.push({ id: label, docId: null, label, total: ms, left: ms, status: 'waiting' });
  }
  return { tasks, elapsed: 0, done: false, facts: {} };
}

function tick(s: State, ms: number): State {
  let docs = s.docs;
  const left = { ...s.left };
  let changed = false;
  docs = docs.map((d) => {
    if (d.phase === 'uploading') {
      changed = true;
      const progress = Math.min(100, d.progress + ms / Math.max(8, d.size / 120_000));
      if (progress < 100) return { ...d, progress };
      left[d.id] = PHASE_MS.reading;
      return { ...d, progress: 100, phase: 'reading' };
    }
    if (d.phase === 'reading' || d.phase === 'classifying' || d.phase === 'speakers') {
      changed = true;
      const rest = (left[d.id] ?? 0) - ms;
      if (rest > 0) {
        left[d.id] = rest;
        return d;
      }
      if (d.phase === 'reading' && d.error) return { ...d, phase: 'failed' };
      if (d.phase === 'reading') {
        left[d.id] = PHASE_MS.classifying;
        return { ...d, phase: 'classifying' };
      }
      if (d.phase === 'classifying' && d.type === 'call-transcript' && s.mock.modelOn) {
        left[d.id] = PHASE_MS.speakers;
        return { ...d, phase: 'speakers' };
      }
      delete left[d.id];
      const out: Doc = { ...d, phase: 'review' };
      if (d.type === 'call-transcript' && !s.mock.modelOn) out.speakers = [];
      if (d.type === 'call-transcript' && s.mock.modelOn) out.speakers = d.speakers.map((x) => ({ ...x, side: x.proposed }));
      return out;
    }
    return d;
  });
  let run = s.run;
  if (run && !run.done) {
    changed = true;
    let budget = ms;
    const tasks = run.tasks.map((t) => ({ ...t }));
    for (const t of tasks) {
      if (t.status === 'done') continue;
      if (budget <= 0) break;
      t.status = 'running';
      const used = Math.min(t.left, budget);
      t.left -= used;
      budget -= used;
      if (t.left <= 0) t.status = 'done';
    }
    const done = tasks.every((t) => t.status === 'done');
    const facts = { ...run.facts };
    for (const t of tasks) {
      if (t.docId && t.status === 'done' && t.label === 'Save' && facts[t.docId] === undefined) {
        const d = s.docs.find((x) => x.id === t.docId);
        facts[t.docId] = d ? Math.max(4, Math.round(d.units * 0.21)) : 0;
      }
    }
    run = { tasks, elapsed: run.elapsed + ms, done, facts };
    if (done) {
      setTimeout(() => ToastQueue.positive('Extraction finished: the fact list is ready', { timeout: 6000 }), 0);
    }
  }
  return changed ? { ...s, docs, left, run } : s;
}

function reducer(s: State, a: Action): State {
  switch (a.type) {
    case 'view':
      return { ...s, view: a.view };
    case 'step':
      return { ...s, step: a.step };
    case 'details':
      return { ...s, details: { ...s.details, ...a.patch } };
    case 'add': {
      const docs = a.docs.map((d, i) => (a.fail && i === 0 ? { ...d, error: 'The file could not be read. It may be damaged or protected with a password.' } : d));
      return { ...s, docs: [...s.docs, ...docs], mock: a.fail ? { ...s.mock, failNext: false } : s.mock };
    }
    case 'tick':
      return tick(s, a.ms);
    case 'patch':
      return { ...s, docs: s.docs.map((d) => (d.id === a.id ? { ...d, ...a.patch } : d)) };
    case 'confirm':
      return { ...s, docs: s.docs.map((d) => (a.ids.includes(d.id) && d.phase === 'review' ? { ...d, confirmed: true, phase: 'confirmed' } : d)) };
    case 'remove':
      return { ...s, docs: s.docs.filter((d) => !a.ids.includes(d.id)) };
    case 'retry':
      return { ...s, docs: s.docs.map((d) => (d.id === a.id ? { ...d, error: null, phase: 'uploading', progress: 0 } : d)) };
    case 'side':
      return {
        ...s,
        docs: s.docs.map((d) => (d.id !== a.docId ? d : {
          ...d,
          speakersConfirmed: false,
          speakers: d.speakers.map((x) => (x.id === a.speakerId ? { ...x, side: a.side, actsFor: a.actsFor ?? (a.side === 'other' ? x.actsFor : '') } : x)),
        })),
      };
    case 'acceptSides':
      return { ...s, docs: s.docs.map((d) => (d.id !== a.docId ? d : { ...d, speakers: d.speakers.map((x) => ({ ...x, side: x.side || x.proposed })) })) };
    case 'confirmSpeakers':
      return { ...s, docs: s.docs.map((d) => (d.id === a.docId ? { ...d, speakersConfirmed: true } : d)) };
    case 'votes':
      return { ...s, votes: a.votes };
    case 'notify':
      return { ...s, notify: a.on };
    case 'start':
      return { ...s, step: 'run', run: startRun(s) };
    case 'mock':
      return { ...s, mock: { ...s.mock, ...a.patch } };
    case 'reset':
      return initial(s.mock);
    case 'sample': {
      const docs = a.docs.map((d, i) => (a.fail && i === 2 ? { ...d, error: 'The file could not be read. It may be damaged or protected with a password.' } : d));
      return {
        ...initial({ ...s.mock, failNext: false }), view: 'intake', step: 'documents',
        details: { name: 'Transit Hub CCTV replacement', customer: 'City of Albany', dealId: 'OPP-20417', due: '2027-06-24', owner: 'Tom Okafor',
          team: [{ name: 'Tom Okafor', role: 'Bid manager' }, { name: 'Lena Voss', role: 'Solution lead' }] },
        docs,
      };
    }
  }
}

interface Ctx {
  s: State;
  go: (step: Step) => void;
  view: (view: View) => void;
  setDetails: (patch: Partial<Details>) => void;
  addFiles: (files: { name: string; size: number }[]) => void;
  addSamples: () => void;
  patch: (id: string, patch: Partial<Doc>) => void;
  setType: (id: string, type: DocType) => void;
  confirm: (ids: string[]) => void;
  remove: (ids: string[]) => void;
  retry: (id: string) => void;
  setSide: (docId: string, speakerId: string, side: Side, actsFor?: '' | 'buyer' | 'ours') => void;
  acceptSides: (docId: string) => void;
  confirmSpeakers: (docId: string) => void;
  setVotes: (v: number) => void;
  setNotify: (on: boolean) => void;
  start: () => void;
  setMock: (patch: Partial<Mock>) => void;
  reset: () => void;
  loadSample: () => void;
}

const C = createContext<Ctx | null>(null);

export function IntakeProvider({ children }: { children: ReactNode }) {
  const [s, dispatch] = useReducer(reducer, undefined, () => initial());
  const busy = s.docs.some((d) => ['uploading', 'reading', 'classifying', 'speakers'].includes(d.phase)) || (s.run !== null && !s.run.done);
  useEffect(() => {
    if (!busy) return;
    const step = 120;
    const id = window.setInterval(() => dispatch({ type: 'tick', ms: step * s.mock.speed }), step);
    return () => window.clearInterval(id);
  }, [busy, s.mock.speed]);

  const ctx = useMemo<Ctx>(() => {
    const nextNo = () => s.docs.reduce((n, d) => Math.max(n, d.no), 0) + 1;
    return {
      s,
      go: (step) => dispatch({ type: 'step', step }),
      view: (view) => dispatch({ type: 'view', view }),
      setDetails: (patch) => dispatch({ type: 'details', patch }),
      addFiles: (files) => {
        const taken = new Set(s.docs.map((d) => d.name));
        const fresh = files.filter((f) => !taken.has(f.name));
        if (fresh.length < files.length) ToastQueue.neutral(`${files.length - fresh.length} already in this bid, not added again`, { timeout: 4000 });
        const start = nextNo();
        const docs = fresh.map((f, i) => {
          const sample = SAMPLES.find((x) => x.name === f.name);
          return newDoc(sample && s.mock.modelOn ? { ...sample, size: f.size } : guess(f.name, f.size, s.mock.modelOn), start + i);
        });
        if (docs.length) dispatch({ type: 'add', docs, fail: s.mock.failNext });
      },
      addSamples: () => ctx.addFiles(SAMPLES.map((x) => ({ name: x.name, size: x.size }))),
      patch: (id, patch) => dispatch({ type: 'patch', id, patch }),
      setType: (id, type) => dispatch({ type: 'patch', id, patch: { type } }),
      confirm: (ids) => dispatch({ type: 'confirm', ids }),
      remove: (ids) => dispatch({ type: 'remove', ids }),
      retry: (id) => dispatch({ type: 'retry', id }),
      setSide: (docId, speakerId, side, actsFor) => dispatch({ type: 'side', docId, speakerId, side, actsFor }),
      acceptSides: (docId) => dispatch({ type: 'acceptSides', docId }),
      confirmSpeakers: (docId) => dispatch({ type: 'confirmSpeakers', docId }),
      setVotes: (votes) => dispatch({ type: 'votes', votes }),
      setNotify: (on) => dispatch({ type: 'notify', on }),
      start: () => dispatch({ type: 'start' }),
      setMock: (patch) => dispatch({ type: 'mock', patch }),
      reset: () => dispatch({ type: 'reset' }),
      loadSample: () => dispatch({ type: 'sample', fail: s.mock.failNext,
        docs: SAMPLES.map((x, i) => newDoc(s.mock.modelOn ? x : guess(x.name, x.size, false), i + 1)) }),
    };
  }, [s]);
  return <C.Provider value={ctx}>{children}</C.Provider>;
}

export function useIntake(): Ctx {
  const c = useContext(C);
  if (!c) throw new Error('useIntake outside IntakeProvider');
  return c;
}
