import { useCallback, useEffect, useRef, useState } from 'react';
import { ToastQueue } from '@adobe/react-spectrum';
import * as api from './api';
import { useAsync, useDebounced } from './hooks';
import { errorText } from './store';
import { pageFromHash } from './nav';
import type { Step } from './intake';
import type { Bid, BidDocumentPatch, BidPlan, BidSummary, BidTeamMember, ExtractJob, RunInfo, Status } from './types';


function readBidParam(): string | null {
  return new URLSearchParams(window.location.search).get('bid');
}
function writeBidParam(bid: string | null) {
  const u = new URL(window.location.href);
  if ((u.searchParams.get('bid') ?? null) === bid) return;
  if (bid === null) u.searchParams.delete('bid');
  else u.searchParams.set('bid', bid);
  window.history.replaceState(null, '', u);
}

/** What the details step edits: saved to the server when the reader leaves the step. */
export interface Details {
  name: string;
  deal_id: string;
  customer: string;
  due: string | null;
  team: BidTeamMember[];
}
const EMPTY_DETAILS: Details = { name: '', deal_id: '', customer: '', due: null, team: [] };
const detailsOf = (b: Bid | null): Details => b
  ? { name: b.name, deal_id: b.deal_id, customer: b.customer, due: b.due, team: b.team.map((t) => ({ name: t.name, role: t.role })) }
  : EMPTY_DETAILS;
const sameDetails = (a: Details, b: Details) => JSON.stringify(a) === JSON.stringify(b);

/** A file on its way up, or one the server refused. */
export interface UploadItem {
  key: number;
  bidId: string;
  name: string;
  size: number;
  /** Kept so that "Try again" can send it once more. */
  file: File;
  status: 'pending' | 'error';
  error: string;
}

/**
 * State of the Documents page: the list of bids, the bid open in the wizard, its uploads, its plan and its extraction.
 * It lives above the pages (in App) so that an extraction keeps being followed, and finishes into the run list, while
 * another page is open. A bid with no extracted document has no run, so nothing here needs the RunProvider.
 */
export function useBidFlow(status: Status | null, refreshRuns: () => Promise<RunInfo[]>, selectRun: (r: string) => void) {
  const [bids, setBids] = useState<BidSummary[] | null>(null);
  const [bidsError, setBidsError] = useState<string | null>(null);
  const [bidParam, setBidParam] = useState<string | null>(readBidParam);
  // A bid is open in the wizard (`?bid=` in the URL opens it), or a new one is being made, or neither: the list.
  const [opened, setOpened] = useState(() => readBidParam() !== null);
  const [drafting, setDrafting] = useState(false);
  const [step, setStep] = useState<Step>('documents');
  const [bid, setBid] = useState<Bid | null>(null);
  const [bidError, setBidError] = useState<string | null>(null);
  const [uploads, setUploads] = useState<UploadItem[]>([]);
  const [details, setDetails] = useState<Details>(EMPTY_DETAILS);
  const [votes, setVotes] = useState(3);
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobBid, setJobBid] = useState<string | null>(null);
  const [jobDocs, setJobDocs] = useState<number[]>([]);
  const [job, setJob] = useState<ExtractJob | null>(null);
  const [startError, setStartError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  const refreshBids = useCallback(async () => {
    try {
      const b = await api.getBids();
      setBids(b);
      setBidsError(null);
      return b;
    } catch (e) {
      setBidsError(errorText(e));
      setBids((cur) => cur ?? []);
      return [] as BidSummary[];
    }
  }, []);
  useEffect(() => void refreshBids(), [refreshBids]);

  // The bid open in the wizard; none while the list shows or a new bid is being made.
  const bidId = opened && !drafting && bidParam && (bids === null || bids.some((b) => b.bid_id === bidParam)) ? bidParam : null;
  useEffect(() => {
    if (bids !== null) writeBidParam(bidId);
  }, [bidId, bids]);
  const showing = bidId !== null || drafting;

  // Which bid the job is for, and whether it still runs, for the places that choose a step.
  const jobState = useRef<{ bid: string | null; status: ExtractJob['status'] | null }>({ bid: null, status: null });
  jobState.current = { bid: jobBid, status: job?.status ?? null };
  const selectBid = useCallback((id: string) => {
    setDrafting(false);
    setBidParam(id);
    setOpened(true);
    setStep(jobState.current.bid === id && jobState.current.status === 'running' ? 'run' : 'documents');
  }, []);
  const startNew = useCallback(() => {
    setDrafting(true);
    setOpened(true);
    setDetails(EMPTY_DETAILS);
    setBid(null);
    setStep('details');
  }, []);
  /** Back to the list of bids. */
  const closeBid = useCallback(() => {
    setDrafting(false);
    setOpened(false);
    setBid(null);
  }, []);

  // Load the selected bid; an answer for a bid that is no longer selected is dropped.
  const current = useRef<string | null>(null);
  current.current = bidId;
  const loadBid = useCallback(async () => {
    const id = current.current;
    if (!id) return null;
    try {
      const b = await api.getBid(id);
      if (current.current !== id) return null;
      setBid(b);
      setBidError(null);
      return b;
    } catch (e) {
      if (current.current === id) setBidError(errorText(e));
      return null;
    }
  }, []);
  // The details form starts from the bid when it is opened; a reload after another change leaves what the reader typed.
  const shown = useRef<string | null>(null);
  useEffect(() => {
    setBid(null);
    setBidError(null);
    shown.current = null;
    // uploads still going up into the bid just opened stay; those of another bid go
    setUploads((u) => u.filter((x) => x.bidId === bidId));
    if (bidId) void loadBid();
  }, [bidId, loadBid]);
  useEffect(() => {
    if (bid && shown.current !== bid.bid_id) {
      shown.current = bid.bid_id;
      setDetails(detailsOf(bid));
    }
  }, [bid]);
  const detailsChanged = !sameDetails(details, bid ? detailsOf(bid) : EMPTY_DETAILS);

  /** After any change of the documents: the bid again, and the list of bids (document counts). */
  const reload = useCallback(async () => {
    await Promise.all([loadBid(), refreshBids()]);
  }, [loadBid, refreshBids]);

  // ---- uploads, one at a time in the order chosen ----
  const nextKey = useRef(1);
  const chain = useRef<Promise<void>>(Promise.resolve());
  const uploadInto = useCallback((id: string, files: File[]) => {
    if (!files.length) return;
    const items = files.map((f) => ({ file: f, item: { key: nextKey.current++, bidId: id, name: f.name, size: f.size, file: f, status: 'pending', error: '' } as UploadItem }));
    setUploads((u) => [...u, ...items.map((x) => x.item)]);
    for (const { file, item } of items) {
      chain.current = chain.current.then(async () => {
        try {
          await api.uploadBidDocument(id, file);
          await reload(); // the row comes from the bid before the upload row goes
          setUploads((u) => u.filter((x) => x.key !== item.key));
        } catch (e) {
          setUploads((u) => u.map((x) => (x.key === item.key ? { ...x, status: 'error', error: errorText(e) } : x)));
        }
      });
    }
  }, [reload]);
  const addFiles = useCallback((files: File[]) => {
    const id = current.current;
    if (id) uploadInto(id, files);
  }, [uploadInto]);
  const dismissUpload = useCallback((key: number) => setUploads((u) => u.filter((x) => x.key !== key)), []);
  const retryUpload = useCallback((key: number) => {
    setUploads((u) => {
      const item = u.find((x) => x.key === key);
      if (item) queueMicrotask(() => uploadInto(item.bidId, [item.file]));
      return u.filter((x) => x.key !== key);
    });
  }, [uploadInto]);

  // ---- the details: made on the server when the reader leaves the step with a name, saved after that ----
  const saveDetails = useCallback(async (): Promise<boolean> => {
    const d = details;
    if (!d.name.trim()) return false;
    try {
      const team = d.team.map((t) => ({ name: t.name, role: t.role }));
      const id = current.current;
      if (!id) {
        const b = await api.createBid({ name: d.name.trim(), deal_id: d.deal_id.trim(), customer: d.customer.trim(), due: d.due });
        const made = team.length ? await api.patchBid(b.bid_id, { team }) : b;
        await refreshBids();
        shown.current = made.bid_id;
        setBid(made);
        setDetails(detailsOf(made));
        current.current = made.bid_id; // uploads that follow go into this bid
        setDrafting(false);
        setBidParam(made.bid_id);
        setOpened(true);
        return true;
      }
      if (sameDetails(d, detailsOf(bid))) return true;
      const b = await api.patchBid(id, { name: d.name.trim(), customer: d.customer.trim(), due: d.due, team });
      shown.current = b.bid_id;
      setBid(b);
      setDetails(detailsOf(b));
      await refreshBids();
      return true;
    } catch (e) {
      ToastQueue.negative(errorText(e), { timeout: 8000 });
      return false;
    }
  }, [details, bid, refreshBids]);

  // ---- edits: each shows its own failure and returns whether it worked ----
  const act = useCallback(async (fn: (id: string) => Promise<unknown>): Promise<boolean> => {
    const id = current.current;
    if (!id) return false;
    try {
      await fn(id);
      await reload();
      return true;
    } catch (e) {
      ToastQueue.negative(errorText(e), { timeout: 8000 });
      await reload();
      return false;
    }
  }, [reload]);
  const patchDocument = useCallback((no: number, body: BidDocumentPatch) => act((id) => api.patchBidDocument(id, no, body)), [act]);
  const suggestSpeakers = useCallback((no: number) => act((id) => api.suggestBidSpeakers(id, no)), [act]);
  const removeDocument = useCallback((no: number) => act((id) => api.deleteBidDocument(id, no)), [act]);
  /** A change to each of several documents, one after the other; one reload at the end. Returns how many worked. */
  const patchMany = useCallback(async (items: { no: number; body: BidDocumentPatch }[]): Promise<number> => {
    const id = current.current;
    if (!id) return 0;
    let done = 0;
    let failure = '';
    for (const { no, body } of items) {
      try {
        await api.patchBidDocument(id, no, body);
        done += 1;
      } catch (e) {
        failure = `d${no}: ${errorText(e)}`;
      }
    }
    if (failure) ToastQueue.negative(failure, { timeout: 8000 });
    await reload();
    return done;
  }, [reload]);
  const removeMany = useCallback(async (nos: number[]): Promise<number> => {
    const id = current.current;
    if (!id) return 0;
    let done = 0;
    let failure = '';
    for (const no of nos) {
      try {
        await api.deleteBidDocument(id, no);
        done += 1;
      } catch (e) {
        failure = `d${no}: ${errorText(e)}`;
      }
    }
    if (failure) ToastQueue.negative(failure, { timeout: 8000 });
    await reload();
    return done;
  }, [reload]);
  const setPrecedence = useCallback((order: string[] | null) => act((id) => api.patchBid(id, { precedence: order })), [act]);

  // ---- the plan: no model call; asked again, after a short pause, whenever the documents or the accuracy change ----
  const sig = bid ? JSON.stringify(bid.documents.map((d) => [
    d.no, d.confirmed, d.playbook, d.issue_number, d.issue_date, d.previous, d.speakers_confirmed, d.run, d.speakers.map((s) => s.side),
  ])) : '';
  const planKey = useDebounced(`${sig}|${votes}`, 400);
  const planned = useAsync<{ bid: string; plan: BidPlan }>(
    (signal) => api.planBid(bidId as string, votes, signal).then((plan) => ({ bid: bidId as string, plan })),
    [bidId, planKey],
    !!bidId && !!bid && bid.documents.length > 0,
  );
  const plan: BidPlan | null = bid && planned.data?.bid === bidId && bid.documents.length > 0 ? planned.data.plan : null;

  // ---- the job ----
  const finished = useRef<string | null>(null);
  useEffect(() => {
    if (!jobId) return;
    let stop = false;
    const tick = async () => {
      try {
        const j = await api.getExtractJob(jobId);
        if (stop) return;
        setJob(j);
        if (j.status === 'running') return;
        stop = true;
        window.clearInterval(timer);
        if (j.status === 'done' && finished.current !== jobId) {
          finished.current = jobId;
          await Promise.all([refreshRuns(), reload()]);
          if (j.run) {
            // On the Documents page the results are right there (with no run open the app is that page, and the URL has no `run`);
            // elsewhere, say so and offer the fact list.
            const onDocuments = pageFromHash(window.location.hash) === 'documents' || !new URLSearchParams(window.location.search).get('run');
            if (!onDocuments) {
              const run = j.run;
              ToastQueue.positive('Extraction finished', {
                timeout: 12000,
                actionLabel: 'Open the facts',
                onAction: () => {
                  window.location.hash = '#/overview';
                  selectRun(run);
                },
              });
            }
          }
        }
      } catch (e) {
        if (stop) return;
        stop = true;
        window.clearInterval(timer);
        setJob({ status: 'failed', seconds: 0, result: null, run: null, error: errorText(e) });
      }
    };
    const timer = window.setInterval(() => void tick(), 2000);
    void tick();
    return () => {
      stop = true;
      window.clearInterval(timer);
    };
    // refreshRuns, reload and selectRun are stable enough for one job
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  const running = starting || job?.status === 'running';
  const start = async () => {
    const id = current.current;
    if (!id) return;
    setStartError(null);
    setStarting(true);
    setJob(null);
    try {
      const r = await api.processBid(id, { votes });
      setJob({ status: 'running', seconds: 0, result: null, run: null, error: null, steps: [] });
      setJobBid(id);
      setJobDocs((plan?.documents ?? []).filter((d) => d.missing.length === 0 && !d.error).map((d) => d.no));
      setJobId(r.job_id);
      setStep('run');
    } catch (e) {
      const msg = errorText(e);
      setStartError(msg);
      ToastQueue.negative(msg, { timeout: 8000 });
    } finally {
      setStarting(false);
    }
  };
  /** Open the fact list of the open bid. */
  const openFacts = useCallback((runPath: string) => {
    window.location.hash = '#/overview';
    selectRun(runPath);
  }, [selectRun]);

  return {
    status, bids, bidsError, refreshBids, bidId, showing, drafting, selectBid, startNew, closeBid, step, setStep,
    bid, bidError, reload, uploads, addFiles, dismissUpload, retryUpload,
    details, setDetails, detailsChanged, saveDetails,
    patchDocument, patchMany, removeMany, suggestSpeakers, removeDocument, setPrecedence,
    votes, setVotes, plan, planLoading: planned.loading, planError: planned.error, replan: planned.reload,
    job: jobBid === bidId ? job : null, jobDocs,
    /** The bid whose extraction runs now, if any. */
    readingBid: job?.status === 'running' ? jobBid : null,
    running, start, startError, openFacts,
  };
}
export type BidFlow = ReturnType<typeof useBidFlow>;
