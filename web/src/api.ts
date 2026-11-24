import { SseParser } from './sse';
import { factsListQuery } from './factsQuery';
import type {
  Bid, BidDocument, BidDocumentPatch, BidLines, BidPatch, BidPlan, BidSummary,
  ChatEvent, ChatMessage, ChatSession, ChatSessionDetail, CompareResponse, Conflict, CorrectionEntry, ExtractJob, Fact,
  FactPatch, FactsListFilters, FactsListResponse, FactsResponse, NewFact, OverviewResponse,
  Report, ResolveBody, RunInfo, RunsTableRow, Status, SummariesResponse, TimelineRow, ViewName,
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
/** Link target for the "Download CSV" button: the same filters as the list. `external` leaves out internal sources. */
export const factsCsvUrl = (run: string, filters: FactsListFilters, audience?: 'external') =>
  `/api/facts.csv?${factsListQuery(run, filters)}${audience ? `&audience=${audience}` : ''}`;

export const getReport = (run: string, signal?: AbortSignal) => request<Report>('GET', `/report?${q({ run })}`, undefined, signal);
export const getRunsTable = (signal?: AbortSignal) => request<RunsTableRow[]>('GET', '/runs/table', undefined, signal);
export const getTimeline = (run: string, factIds: string[], signal?: AbortSignal) =>
  request<{ rows: TimelineRow[] }>('GET', `/timeline?${q({ run, fact_ids: factIds.join(',') })}`, undefined, signal);

export const getCompare = (a: string, b: string, signal?: AbortSignal) =>
  request<CompareResponse>('GET', `/compare?${q({ a, b })}`, undefined, signal);

// ---- Bids ----

export const getBids = () => request<BidSummary[]>('GET', '/bids');
export const createBid = (body: { name: string; deal_id?: string; customer?: string; due?: string | null }) => request<Bid>('POST', '/bids', body);
export const getBid = (bid: string, signal?: AbortSignal) => request<Bid>('GET', `/bids/${enc(bid)}`, undefined, signal);
export const patchBid = (bid: string, body: BidPatch) => request<Bid>('PATCH', `/bids/${enc(bid)}`, body);
/** The raw file is the body; the server reads the type from the name. */
export const uploadBidDocument = (bid: string, file: File) =>
  send<BidDocument>('POST', `/bids/${enc(bid)}/documents?${q({ name: file.name })}`, file, 'application/octet-stream');
export const patchBidDocument = (bid: string, no: number, body: BidDocumentPatch) =>
  request<BidDocument>('PATCH', `/bids/${enc(bid)}/documents/${no}`, body);
/** Ask the model again who is on which side of a call; the document entry comes back. */
export const suggestBidSpeakers = (bid: string, no: number) =>
  request<BidDocument>('POST', `/bids/${enc(bid)}/documents/${no}/speakers/suggest`, {});
/** The lines of a call in order, with who speaks each. Only a call has them (else a 400). */
export const getBidDocumentLines = (bid: string, no: number, limit?: number, signal?: AbortSignal) =>
  request<BidLines>('GET', `/bids/${enc(bid)}/documents/${no}/lines${limit === undefined ? '' : `?${q({ limit })}`}`, undefined, signal);
export const deleteBidDocument = (bid: string, no: number) =>
  request<{ ok: true }>('DELETE', `/bids/${enc(bid)}/documents/${no}`);
export const planBid = (bid: string, votes?: number, signal?: AbortSignal) =>
  request<BidPlan>('POST', `/bids/${enc(bid)}/plan`, votes === undefined ? {} : { votes }, signal);
export const processBid = (bid: string, body: { votes?: number; model?: string } = {}) =>
  request<{ job_id: string }>('POST', `/bids/${enc(bid)}/process`, { ...body, confirm: true });
export const getExtractJob = (jobId: string) => request<ExtractJob>('GET', `/extract/${enc(jobId)}`);

/** `doc` (a doc_id) names the document of a bid whose page is drawn. */
export const pageImageUrl = (run: string, page: number, factId: string, doc?: string) =>
  `/api/page?${q({ run, page, fact_id: factId, doc })}`;

// ---- Relations and groups of a bid ----

export const rejectRelation = (run: string, rid: string) =>
  request<{ ok: true }>('POST', `/relations/${enc(rid)}/reject?${q({ run })}`);
export const ungroup = (run: string, gid: string) =>
  request<{ ok: true }>('POST', `/groups/${enc(gid)}/ungroup?${q({ run })}`);

export const getChat = (run: string) => request<ChatMessage[]>('GET', `/chat?${q({ run })}`);
export const clearChat = (run: string) => request<{ ok: true }>('DELETE', `/chat?${q({ run })}`);
export const getChatSessions = (run: string) => request<ChatSession[]>('GET', `/chat/sessions?${q({ run })}`);
export const getChatSession = (run: string, sessionId: string) =>
  request<ChatSessionDetail>('GET', `/chat/sessions/${enc(sessionId)}?${q({ run })}`);
export interface DeletedSessions { ok: true; deleted: string[]; chat_cleared: boolean }
export const deleteChatSession = (run: string, sessionId: string) =>
  request<DeletedSessions>('DELETE', `/chat/sessions/${enc(sessionId)}?${q({ run })}`);
export const deleteChatSessions = (run: string) => request<DeletedSessions>('DELETE', `/chat/sessions?${q({ run })}`);

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
