import { SseParser } from './sse';
import { factsListQuery } from './factsQuery';
import type {
  ChatEvent, ChatMessage, CompareResponse, Conflict, CorrectionEntry, ExtractJob, ExtractPlan, ExtractRequest, Fact,
  FactPatch, FactsListFilters, FactsListResponse, FactsResponse, NewFact, OverviewResponse, PdfChoice, PdfSource,
  PdfState, Report, ResolveBody, RunInfo, RunsTableRow, Status, SummariesResponse, UploadInfo, ViewName,
} from './types';

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

const q = (params: Record<string, string | number | boolean | undefined>) => {
  const s = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined) s.set(k, String(v));
  return s.toString();
};

async function errorFrom(res: Response): Promise<ApiError> {
  let msg = `${res.status} ${res.statusText}`;
  try {
    const body = await res.json();
    if (body && typeof body.detail === 'string') msg = body.detail;
  } catch {
    /* keep the status line */
  }
  return new ApiError(msg, res.status);
}

async function request<T>(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  return send<T>(method, path, body === undefined ? undefined : JSON.stringify(body),
    body === undefined ? undefined : 'application/json', signal);
}

async function send<T>(method: string, path: string, body?: BodyInit, contentType?: string, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, {
      method,
      signal,
      headers: contentType ? { 'Content-Type': contentType } : undefined,
      body,
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e;
    throw new ApiError('Cannot reach the server. Is it running?', 0);
  }
  if (!res.ok) throw await errorFrom(res);
  return (await res.json()) as T;
}

const enc = encodeURIComponent;

export const getStatus = () => request<Status>('GET', '/status');
export const getRuns = () => request<RunInfo[]>('GET', '/runs');

export const getFacts = (run: string, includeDeleted = true) =>
  request<FactsResponse>('GET', `/facts?${q({ run, include_deleted: includeDeleted ? 1 : undefined })}`);
export const addFact = (run: string, body: NewFact) => request<Fact>('POST', `/facts?${q({ run })}`, body);
export const patchFact = (run: string, factId: string, body: FactPatch) =>
  request<Fact>('PATCH', `/facts/${enc(factId)}?${q({ run })}`, body);
export const deleteFact = (run: string, factId: string, reason?: string) =>
  request<{ ok: true }>('DELETE', `/facts/${enc(factId)}?${q({ run })}`, reason ? { reason } : undefined);
export const restoreFact = (run: string, factId: string) =>
  request<Fact>('POST', `/facts/${enc(factId)}/restore?${q({ run })}`);

export const getCorrections = (run: string) => request<CorrectionEntry[]>('GET', `/corrections?${q({ run })}`);
export const undoCorrection = (run: string, id: string) =>
  request<{ ok: true }>('POST', `/corrections/${enc(id)}/undo?${q({ run })}`);

export const getConflicts = (run: string) => request<Conflict[]>('GET', `/conflicts?${q({ run })}`);
export const resolveConflict = (run: string, id: string, body: ResolveBody) =>
  request<Conflict>('POST', `/conflicts/${enc(id)}/resolve?${q({ run })}`, body);
export const reopenConflict = (run: string, id: string) =>
  request<Conflict>('POST', `/conflicts/${enc(id)}/reopen?${q({ run })}`);

export const getSummaries = (run: string, signal?: AbortSignal) =>
  request<SummariesResponse>('GET', `/summaries?${q({ run })}`, undefined, signal);
export const generateSummaries = (run: string, sections?: string[]) =>
  request<SummariesResponse>('POST', `/summaries/generate?${q({ run })}`, sections ? { sections } : {});

// ---- Overview, filtered facts, report, compare, PDFs, new run (spec 11.1) ----

export const getOverview = (run: string, view: ViewName, signal?: AbortSignal) =>
  request<OverviewResponse>('GET', `/overview?${q({ run, view })}`, undefined, signal);

export const getFactsList = (run: string, filters: FactsListFilters, signal?: AbortSignal) =>
  request<FactsListResponse>('GET', `/facts/list?${factsListQuery(run, filters)}`, undefined, signal);
/** Link target for the "Download CSV" button: the same filters as the list. */
export const factsCsvUrl = (run: string, filters: FactsListFilters) => `/api/facts.csv?${factsListQuery(run, filters)}`;

export const getReport = (run: string, signal?: AbortSignal) => request<Report>('GET', `/report?${q({ run })}`, undefined, signal);
export const getRunsTable = (signal?: AbortSignal) => request<RunsTableRow[]>('GET', '/runs/table', undefined, signal);
export const getCompare = (a: string, b: string, signal?: AbortSignal) =>
  request<CompareResponse>('GET', `/compare?${q({ a, b })}`, undefined, signal);

export const getPdfs = (signal?: AbortSignal) => request<PdfChoice[]>('GET', '/pdfs', undefined, signal);
export const attachPdfPath = (run: string, path: string) => request<PdfState>('PUT', `/pdf?${q({ run })}`, { path });
export const attachPdfUpload = (run: string, file: File) =>
  send<PdfState>('PUT', `/pdf?${q({ run, name: file.name })}`, file, 'application/pdf');
export const detachPdf = (run: string) => request<PdfState>('DELETE', `/pdf?${q({ run })}`);

export const uploadPdf = (file: File) => send<UploadInfo>('POST', `/uploads?${q({ name: file.name })}`, file, 'application/pdf');
export const planExtract = (source: PdfSource, doc_id: string, votes: number) =>
  request<ExtractPlan>('POST', '/extract/plan', { ...source, doc_id, votes });
export const startExtract = (source: PdfSource, body: ExtractRequest) =>
  request<{ job_id: string }>('POST', '/extract', { ...source, ...body });
export const getExtractJob = (jobId: string) => request<ExtractJob>('GET', `/extract/${enc(jobId)}`);

export const pageImageUrl = (run: string, page: number, factId: string) =>
  `/api/page?${q({ run, page, fact_id: factId })}`;

export const getChat = (run: string) => request<ChatMessage[]>('GET', `/chat?${q({ run })}`);
export const clearChat = (run: string) => request<{ ok: true }>('DELETE', `/chat?${q({ run })}`);

/**
 * Send a chat message and read the text/event-stream response. `onEvent` is called for
 * each event as it arrives. Resolves when the stream ends; rejects with ApiError on a
 * non-2xx response or a network failure.
 */
export async function streamChat(
  run: string,
  message: string,
  onEvent: (e: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`/api/chat?${q({ run })}`, {
      method: 'POST',
      signal,
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify({ message }),
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e;
    throw new ApiError('Cannot reach the server. Is it running?', 0);
  }
  if (!res.ok) throw await errorFrom(res);
  if (!res.body) throw new ApiError('The server sent no stream.', 0);
  await readEventStream(res.body, onEvent);
}

export async function readEventStream(body: ReadableStream<Uint8Array>, onEvent: (e: ChatEvent) => void) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  const parser = new SseParser();
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    for (const ev of parser.push(decoder.decode(value, { stream: true }))) onEvent(ev);
  }
  for (const ev of parser.push(decoder.decode())) onEvent(ev);
  for (const ev of parser.flush()) onEvent(ev);
}
