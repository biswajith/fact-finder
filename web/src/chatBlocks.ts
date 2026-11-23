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
