// Splits assistant text into Markdown parts and block parts: `[[source:ID]]` and `[[timeline:ID,ID,...]]`,
// each alone on its own line. The model only names facts; the blocks are drawn from stored data.

export type Block =
  | { kind: 'text'; text: string }
  | { kind: 'source'; factId: string }
  | { kind: 'timeline'; factIds: string[] };

const ID = '[fu]_[0-9a-f]{10}';
const SOURCE = new RegExp(`^\\[\\[source:(${ID})\\]\\]$`);
const TIMELINE = new RegExp(`^\\[\\[timeline:(${ID}(?:,${ID})+)\\]\\]$`);
export const MAX_TIMELINE_IDS = 12;
const FENCE = /^\s*(```|~~~)/;

function parseLine(line: string): Block | null {
  const t = line.trim();
  const s = SOURCE.exec(t);
  if (s) return { kind: 'source', factId: s[1] };
  const m = TIMELINE.exec(t);
  if (m) {
    const ids = m[1].split(',');
    if (ids.length <= MAX_TIMELINE_IDS) return { kind: 'timeline', factIds: ids };
  }
  return null;
}

/**
 * Text parts and block parts in order. A token that is not alone on its line, is malformed, or sits in a code
 * fence stays text. With `streaming`, an unfinished last line that starts with `[[` is held back until it ends.
 */
export function splitBlocks(text: string, opts: { streaming?: boolean } = {}): Block[] {
  // The model sometimes writes a marker inside a sentence: such a line is cut so each marker has its own line.
  const MARK = /\[\[(?:source|timeline):[^\[\]\n]*\]\]/g;
  const lines = text.split('\n').flatMap((line) => {
    const rest = line.replace(MARK, '').trim();
    if (!rest || rest === '-' || rest === '*' || !MARK.test(line)) return [line];
    MARK.lastIndex = 0;
    return line.split(/(\[\[(?:source|timeline):[^\[\]\n]*\]\])/).map((x) => x.trim()).filter(Boolean);
  });
  if (opts.streaming && lines[lines.length - 1].trimStart().startsWith('[[')) lines.pop();
  const out: Block[] = [];
  let buf: string[] = [];
  let fence = '';
  const flush = () => {
    const t = buf.join('\n');
    if (t.trim()) out.push({ kind: 'text', text: t });
    buf = [];
  };
  for (const line of lines) {
    const f = FENCE.exec(line)?.[1];
    if (f) fence = fence === '' ? f : fence === f ? '' : fence;
    const block = fence || f ? null : parseLine(line);
    if (block) {
      flush();
      out.push(block);
    } else {
      buf.push(line);
    }
  }
  flush();
  return out;
}


/** The steps of a plan the assistant is waiting on, one per line, for the reader to edit. */
export function planLines(p: { plan_text?: string; steps?: { step: string }[]; plan_steps?: { step: string; covers?: string[] }[] } | null | undefined): string {
  if (p?.steps?.length) return p.steps.map((x, i) => `${i + 1}. ${x.step}`).join('\n');
  if (p?.plan_steps?.length)
    return p.plan_steps.map((x, i) => `${i + 1}. ${x.step}${x.covers?.length ? ` (covers: ${x.covers.join(', ')})` : ''}`).join('\n');
  const text = (p?.plan_text ?? '').replace(/^\s*Plan:\s*/i, '').trim();
  // "1. look up; 2. report" or "1) look up 2) report" becomes one step a line
  const parts = text.split(/\s*;?\s*(?=\d+[.)]\s)/).map((x) => x.trim().replace(/;$/, '')).filter(Boolean);
  return parts.length > 1 ? parts.join('\n') : text;
}

export interface PlanStep { text: string; items: string[]; done: boolean }

/** A list at the end of a step ("..., including scope, volumes, and terms") as separate items,
 * so a long run of topics can be shown as tags. Fewer than three items stay in the sentence. */
function stepItems(step: string): { text: string; items: string[] } {
  const m = step.match(/^(.*?)(?:,\s*|\s+)(?:including|such as|covering)\s+(.+?)\.?$/i);
  if (!m) return { text: step, items: [] };
  const items = m[2].split(/\s*,\s*(?:and\s+|or\s+)?|\s+and\s+(?=[^,]*$)/).map((x) => x.trim()).filter(Boolean);
  return items.length >= 3 ? { text: m[1].trim(), items } : { text: step, items: [] };
}

/** An assistant message that shows a plan ("Plan: 1. ...; 2. ..." or "Plan:\n1. ...") split into
 * its steps and the words after it; null for any other message. */
export function planMessage(
  text: string,
  planning?: { plan_steps?: { step: string; covers?: string[] }[] } | null,
): { steps: PlanStep[]; rest: string } | null {
  const m = text.match(/^\s*Plan:\s*([\s\S]*?)(?:\n\s*\n([\s\S]*))?$/i);
  if (!m) return null;
  // The planner's own steps and topics, when it gave them; older plans are read from their text.
  if (planning?.plan_steps?.length)
    return { steps: planning.plan_steps.map((x) => ({ text: x.step, items: x.covers ?? [], done: false })), rest: (m[2] ?? '').trim() };
  const lines = planLines({ plan_text: m[1].replace(/\n/g, ' ') }).split('\n');
  const steps = lines
    .map((l) => l.replace(/^\s*\d+[.)]\s*/, '').trim())
    .filter(Boolean)
    .map((l) => {
      const done = /^\[done\]\s*/i.test(l);
      const s = l.replace(/^\[done\]\s*/i, '').replace(/;$/, '');
      const { text: t, items } = stepItems(s);
      return { text: t.charAt(0).toUpperCase() + t.slice(1), items, done };
    });
  return steps.length ? { steps, rest: (m[2] ?? '').trim() } : null;
}
