// Turns `[f_...]` and `[u_...]` references in assistant text into link segments.

export type TextSegment = { kind: 'text'; text: string } | { kind: 'fact'; factId: string };

// `[f_x]` (any length) or a bare id of 8+ characters that is not part of a longer word or path.
const TOKEN = /\[([fu]_[A-Za-z0-9]+)\]|(?<!\]\()(?<![\w\[/:.-])([fu]_[A-Za-z0-9]{8,})(?![\w\]-])/g;

export function splitFactTokens(text: string): TextSegment[] {
  const out: TextSegment[] = [];
  let last = 0;
  for (const m of text.matchAll(TOKEN)) {
    const at = m.index ?? 0;
    if (at > last) out.push({ kind: 'text', text: text.slice(last, at) });
    out.push({ kind: 'fact', factId: m[1] ?? m[2] });
    last = at + m[0].length;
  }
  if (last < text.length) out.push({ kind: 'text', text: text.slice(last) });
  return out;
}

const FENCE_OR_CODE = /(```[\s\S]*?(?:```|$)|~~~[\s\S]*?(?:~~~|$)|`[^`\n]*`)/;
const JOINER = /^\s*(?:,|;|&|and)?\s*$/i;

/**
 * Rewrites fact ids in Markdown as `[](fact:id1,id2)` links (one link per run of ids separated only
 * by spaces, commas or "and"), leaving code spans and fences alone. A run wrapped in its own
 * parentheses or brackets loses them.
 */
export function linkifyFactTokens(md: string): string {
  return md
    .split(FENCE_OR_CODE)
    .map((part, i) => (i % 2 === 1 ? part : linkifyPlain(part)))
    .join('');
}

function linkifyPlain(text: string): string {
  const segs = splitFactTokens(text);
  const out: string[] = [];
  for (let i = 0; i < segs.length; i++) {
    const s = segs[i];
    if (s.kind === 'text') {
      out.push(s.text);
      continue;
    }
    const ids = [s.factId];
    let j = i + 1;
    while (j + 1 < segs.length && segs[j].kind === 'text' && segs[j + 1].kind === 'fact' && JOINER.test((segs[j] as { text: string }).text)) {
      ids.push((segs[j + 1] as { factId: string }).factId);
      j += 2;
    }
    const link = `[](fact:${ids.join(',')})`;
    const prev = out[out.length - 1];
    const next = segs[j];
    {
      const wrapped = prev !== undefined && /[(\[]$/.test(prev) && next?.kind === 'text' && /^[)\]]/.test(next.text);
      if (wrapped) {
        out[out.length - 1] = prev.slice(0, -1);
        (segs[j] as { text: string }).text = next.text.slice(1);
      }
    }
    out.push(link);
    i = j - 1;
  }
  return out.join('');
}
