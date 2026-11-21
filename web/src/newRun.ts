import { useCallback, useEffect, useRef, useState } from 'react';
import { ToastQueue } from '@adobe/react-spectrum';
import * as api from './api';
import { useAsync, useDebounced } from './hooks';
import { errorText } from './store';
import type { ExtractJob, ExtractPlan, PdfSource, RunInfo, Status, UploadInfo } from './types';

export const VOTES = [1, 3, 5] as const;

/** Doc ID suggested for a file: its name without the extension. */
export const stemOf = (name: string) => name.replace(/\.[^./\\]+$/, '');

/** Which of the things an extraction needs are still missing, in the old app's words. */
export function missingFor(hasPdf: boolean, dealId: string, docId: string): string[] {
  return [['a PDF', hasPdf], ['a deal ID', !!dealId.trim()], ['a doc ID', !!docId.trim()]].filter(([, ok]) => !ok).map(([w]) => w as string);
}

/**
 * State of the New run tab. It lives above the tabs so that an extraction keeps being
 * followed (and finishes into the run list) while another tab is open.
 */
export function useNewRun(status: Status | null, refreshRuns: () => Promise<RunInfo[]>, selectRun: (r: string) => void) {
  const [mode, setMode] = useState<'pick' | 'upload'>('pick');
  const [picked, setPicked] = useState<{ path: string; name: string } | null>(null);
  const [upload, setUpload] = useState<UploadInfo | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [dealId, setDealId] = useState('');
  const [docEdit, setDocEdit] = useState<string | null>(null);
  const [model, setModel] = useState('');
  const [votes, setVotes] = useState<number>(3);
  const [confirmed, setConfirmed] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<ExtractJob | null>(null);
  const [startError, setStartError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  const source: PdfSource | null = mode === 'upload' ? (upload ? { upload_id: upload.upload_id } : null) : picked ? { path: picked.path } : null;
  const fileName = mode === 'upload' ? (upload?.name ?? '') : (picked?.name ?? '');
  const docId = docEdit ?? stemOf(fileName);
  const modelValue = model || status?.model || '';
  const debDoc = useDebounced(docId, 400);
  const sourceKey = source ? JSON.stringify(source) : '';

  // The plan makes no model call. It is asked again when the PDF, the doc ID or the votes change.
  const plan = useAsync<ExtractPlan>(() => api.planExtract(source as PdfSource, debDoc.trim(), votes), [sourceKey, debDoc, votes], !!source && !!debDoc.trim());
  const planOf: ExtractPlan | null = source && debDoc.trim() ? plan.data : null;

  const choosePick = (p: { path: string; name: string } | null) => {
    setPicked(p);
    setDocEdit(null);
  };
  const chooseUpload = useCallback(async (file: File) => {
    setUploading(true);
    setUploadError(null);
    try {
      const info = await api.uploadPdf(file);
      setUpload(info);
      setDocEdit(null);
    } catch (e) {
      setUploadError(errorText(e));
    } finally {
      setUploading(false);
    }
  }, []);

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
        window.clearInterval(id);
        if (j.status === 'done' && finished.current !== jobId) {
          finished.current = jobId;
          setConfirmed(false); // the next run needs a fresh confirmation
          await refreshRuns();
          if (j.run) selectRun(j.run);
        }
      } catch (e) {
        if (stop) return;
        stop = true;
        window.clearInterval(id);
        setJob({ status: 'failed', seconds: 0, result: null, run: null, error: errorText(e) });
      }
    };
    const id = window.setInterval(() => void tick(), 2000);
    void tick();
    return () => {
      stop = true;
      window.clearInterval(id);
    };
    // refreshRuns and selectRun are stable enough for one job
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  const running = starting || job?.status === 'running';
  const missing = missingFor(!!source, dealId, docId);
  const canStart = confirmed && !!status?.has_key && missing.length === 0 && !running;

  const start = async () => {
    if (!source) return;
    setStartError(null);
    setStarting(true);
    setJob(null);
    try {
      const r = await api.startExtract(source, {
        deal_id: dealId.trim(), doc_id: docId.trim(), model: modelValue.trim() || undefined, votes, confirm: true,
      });
      setJob({ status: 'running', seconds: 0, result: null, run: null, error: null });
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
    mode, setMode, picked, choosePick, upload, uploading, uploadError, chooseUpload, fileName,
    dealId, setDealId, docId, setDocEdit, modelValue, setModel, votes, setVotes, confirmed, setConfirmed,
    plan, planOf, hasSource: !!source, missing, canStart, running, job, start, startError, selectRun,
  };
}
export type NewRun = ReturnType<typeof useNewRun>;
