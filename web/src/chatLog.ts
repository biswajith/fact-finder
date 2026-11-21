// Turning a chat session's event log (WEB_UI_SPEC.md 7.2) into turns for the Chat log page. Pure.
import type { ChatLogEvent, ChatTotals } from './types';

/** One model call and the tool runs it asked for (they follow it in the log, before the next call). */
export interface CallRow {
  call: ChatLogEvent;
  tools: ChatLogEvent[];
}

export interface Turn {
  id: string;
  at: string;
  user?: string;
  route?: ChatLogEvent;
  feedback?: ChatLogEvent;
  /** The last plan event of the turn: the plan as it stood when the turn ended. */
  plan?: ChatLogEvent;
  planUpdates: number;
  calls: CallRow[];
  reply?: ChatLogEvent;
  end?: ChatLogEvent;
}

export function groupTurns(events: ChatLogEvent[]): Turn[] {
  const turns: Turn[] = [];
  const byId = new Map<string, Turn>();
  for (const e of [...events].sort((a, b) => (a.turn_id === b.turn_id ? a.seq - b.seq : 0))) {
    let t = byId.get(e.turn_id);
    if (!t) {
      t = { id: e.turn_id, at: e.at, planUpdates: 0, calls: [] };
      byId.set(e.turn_id, t);
      turns.push(t);
    }
    switch (e.event) {
      case 'user_message': t.user = e.text; break;
      case 'route': t.route = e; break;
      case 'feedback': t.feedback = e; break;
      case 'plan': t.plan = e; t.planUpdates += 1; break;
      case 'llm_call': t.calls.push({ call: e, tools: [] }); break;
      case 'tool':
        if (t.calls.length) t.calls[t.calls.length - 1].tools.push(e);
        break;
      case 'assistant_message': t.reply = e; break;
      case 'turn_end': t.end = e; break;
    }
  }
  return turns;
}

/** Turn totals: from turn_end when the turn finished, else summed from its calls. */
export function turnTotals(t: Turn): ChatTotals {
  if (t.end?.totals) return t.end.totals;
  const sum = (k: 'input_tokens' | 'cached_tokens' | 'output_tokens' | 'cost_usd') => t.calls.reduce((n, c) => n + (c.call[k] ?? 0), 0);
  const priced = t.calls.some((c) => c.call.cost_usd != null);
  return {
    llm_calls: t.calls.length,
    tool_calls: t.calls.reduce((n, c) => n + c.tools.length, 0),
    input_tokens: sum('input_tokens'),
    cached_tokens: sum('cached_tokens'),
    output_tokens: sum('output_tokens'),
    ...(priced ? { cost_usd: sum('cost_usd') } : {}),
  };
}

export const fmtNum = (n: number | null | undefined): string => (n == null ? '–' : Math.round(n).toLocaleString('en-US'));

/** Dollars for tiny amounts: two significant figures under a cent ($0.00044), cents above. */
export function fmtUsd(n: number | null | undefined): string {
  if (n == null) return '–';
  if (n === 0) return '$0';
  if (n < 0.01) return '$' + Number(n.toPrecision(2)).toFixed(Math.max(2, 1 - Math.floor(Math.log10(n))));
  return '$' + n.toFixed(2);
}

export const fmtSecs = (s: number | null | undefined): string => (s == null ? '–' : s < 10 ? `${s.toFixed(1)}s` : `${Math.round(s)}s`);

/** Share of input tokens served from the cache, as "83%"; "–" when unknown. */
export function cacheShare(input: number | null | undefined, cached: number | null | undefined): string {
  if (!input) return '–';
  return `${Math.round(((cached ?? 0) / input) * 100)}%`;
}

const PURPOSE_LABEL: Record<string, string> = {
  plan_heavy: 'Write plan (steps)',
  plan_light: 'Write plan (one line)',
  loop: 'Tool round',
  final: 'Final answer',
};
export const purposeLabel = (p?: string): string => (p ? (PURPOSE_LABEL[p] ?? p) : '');

/** A tool call's arguments in a few words: the queries of a search, else key=value pairs. */
export function argsText(args: unknown): string {
  if (!args || typeof args !== 'object' || Array.isArray(args)) return args == null ? '' : String(args);
  const a = args as Record<string, unknown>;
  const parts: string[] = [];
  if (Array.isArray(a.queries)) parts.push(a.queries.map((x) => `“${String(x)}”`).join(', '));
  else if (typeof a.query === 'string' && a.query) parts.push(`“${a.query}”`);
  for (const [k, v] of Object.entries(a)) {
    if (k === 'queries' || k === 'query' || v === undefined || v === null || v === '') continue;
    parts.push(`${k}=${typeof v === 'object' ? JSON.stringify(v) : String(v)}`);
  }
  return parts.join(' · ');
}
