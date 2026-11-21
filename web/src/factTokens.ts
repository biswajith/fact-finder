// Turns `[f_...]` and `[u_...]` references in assistant text into link segments.

export type TextSegment = { kind: 'text'; text: string } | { kind: 'fact'; factId: string };

const TOKEN = /\[([fu]_[A-Za-z0-9]+)\]/g;

export function splitFactTokens(text: string): TextSegment[] {
  const out: TextSegment[] = [];
  let last = 0;
  for (const m of text.matchAll(TOKEN)) {
    const at = m.index ?? 0;
    if (at > last) out.push({ kind: 'text', text: text.slice(last, at) });
    out.push({ kind: 'fact', factId: m[1] });
    last = at + m[0].length;
  }
  if (last < text.length) out.push({ kind: 'text', text: text.slice(last) });
  return out;
}
