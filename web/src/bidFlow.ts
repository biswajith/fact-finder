import { useCallback, useEffect, useRef, useState } from 'react';
import { ToastQueue } from '@adobe/react-spectrum';
import * as api from './api';
import { useAsync, useDebounced } from './hooks';
import { errorText } from './store';
import type { Bid, BidDocumentPatch, BidPlan, BidSummary, ExtractJob, RunInfo, Status } from './types';

const BIDS = '_bids/';

function readBidParam(): string | null {
  return new URLSearchParams(window.location.search).get('bid');
}
function writeBidParam(bid: string) {
  const u = new URL(window.location.href);
  if (u.searchParams.get('bid') === bid) return;
  u.searchParams.set('bid', bid);
  window.history.replaceState(null, '', u);
}

/** A file on its way up, or one the server refused. */
export interface UploadItem {
  key: number;
  bidId: string;
  name: string;
  status: 'pending' | 'error';
  error: string;
}

/**
 * State of the Documents page. It lives above the pages (in App) so that an extraction keeps being followed,
 * and finishes into the run list, while another page is open. A bid with no extracted document has no run,
 * so nothing here needs the RunProvider.
 */
export function useBidFlow(status: Status | null, run: string | null, refreshRuns: () => Promise<RunInfo[]>, selectRun: (r: string) => void) {
  const [bids, setBids] = useState<BidSummary[] | null>(null);
  const [bidsError, setBidsError] = useState<string | null>(null);
  const [bidParam, setBidParam] = useState<string | null>(readBidParam);
  const [newRequested, setNewRequested] = useState(false);
  const [bid, setBid] = useState<Bid | null>(null);
  const [bidError, setBidError] = useState<string | null>(null);
  const [uploads, setUploads] = useState<UploadItem[]>([]);
  const [confirmed, setConfirmed] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobBid, setJobBid] = useState<string | null>(null);
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

  // The bid in the URL; else the open run when it is a bid; else the first bid.
  const bidId =
    bidParam && (bids === null || bids.some((b) => b.bid_id === bidParam)) ? bidParam
      : run?.startsWith(BIDS) ? run.slice(BIDS.length)
        : (bids?.[0]?.bid_id ?? null);
  useEffect(() => {
    if (bidId) writeBidParam(bidId);
  }, [bidId]);
  const selectBid = useCallback((id: string) => {
    setNewRequested(false);
    setBidParam(id);
  }, []);
  const startNew = useCallback(() => setNewRequested(true), []);
  const cancelNew = useCallback(() => setNewRequested(false), []);
  const creating = newRequested || (bids !== null && bids.length === 0);

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
  useEffect(() => {
    setBid(null);
    setBidError(null);
    // uploads still going up into the bid just opened stay; those of another bid go
    setUploads((u) => u.filter((x) => x.bidId === bidId));
    if (bidId) void loadBid();
  }, [bidId, loadBid]);

  /** After any change of the documents: the bid again, and the list of bids (document counts). */
  const reload = useCallback(async () => {
    await Promise.all([loadBid(), refreshBids()]);
  }, [loadBid, refreshBids]);

  // ---- uploads, one at a time in the order chosen ----
  const nextKey = useRef(1);
  const chain = useRef<Promise<void>>(Promise.resolve());
  const uploadInto = useCallback((id: string, files: File[]) => {
    if (!files.length) return;
    const items = files.map((f) => ({ file: f, item: { key: nextKey.current++, bidId: id, name: f.name, status: 'pending', error: '' } as UploadItem }));
    setUploads((u) => [...u, ...items.map((x) => x.item)]);
    for (const { file, item } of items) {
      chain.current = chain.current.then(async () => {
        try {
          await api.uploadBidDocument(id, file);
          setUploads((u) => u.filter((x) => x.key !== item.key));
          await reload();
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

  /** Make the bid and open it; `files` go up into this new bid (by its own id, not the one selected before). */
  const createBid = useCallback(async (name: string, files?: File[]) => {
    const b = await api.createBid(name.trim());
    await refreshBids();
    setNewRequested(false);
    setBidParam(b.bid_id);
    if (files?.length) uploadInto(b.bid_id, files);
    return b;
  }, [refreshBids, uploadInto]);
  const dismissUpload = useCallback((key: number) => setUploads((u) => u.filter((x) => x.key !== key)), []);

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
  const saveTeam = useCallback((names: string[]) => act((id) => api.patchBid(id, { team: names.map((name) => ({ name })) })), [act]);
  const setPrecedence = useCallback((order: string[] | null) => act((id) => api.patchBid(id, { precedence: order })), [act]);

  // ---- the plan: no model call; asked again, after a short pause, whenever the documents change ----
  const sig = bid ? JSON.stringify(bid.documents.map((d) => [
    d.no, d.confirmed, d.playbook, d.issue_number, d.issue_date, d.previous, d.speakers_confirmed, d.run, d.speakers.map((s) => s.side),
  ])) : '';
  const planKey = useDebounced(sig, 400);
  const planned = useAsync<{ bid: string; plan: BidPlan }>(
    (signal) => api.planBid(bidId as string, undefined, signal).then((plan) => ({ bid: bidId as string, plan })),
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
          setConfirmed(false); // the next extraction needs a fresh confirmation
          await Promise.all([refreshRuns(), reload()]);
          if (j.run) {
            window.location.hash = '#/overview';
            selectRun(j.run);
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
      const r = await api.processBid(id);
      setJob({ status: 'running', seconds: 0, result: null, run: null, error: null, steps: [] });
      setJobBid(id);
      setJobId(r.job_id);
    } catch (e) {
      const msg = errorText(e);
      setStartError(msg);
      ToastQueue.negative(msg, { timeout: 8000 });
    } finally {
      setStarting(false);
    }
  };

  return {
    status, bids, bidsError, refreshBids, bidId, selectBid, creating, startNew, cancelNew, createBid, bid, bidError, reload, uploads, addFiles, dismissUpload,
    patchDocument, suggestSpeakers, removeDocument, saveTeam, setPrecedence, plan, planLoading: planned.loading, planError: planned.error, replan: planned.reload,
    confirmed, setConfirmed, job: jobBid === bidId ? job : null, running, start, startError,
  };
}
export type BidFlow = ReturnType<typeof useBidFlow>;
