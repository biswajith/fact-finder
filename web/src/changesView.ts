import { CATEGORY_NAMES } from './types';

export interface DiffPart { text: string; kind: 'same' | 'del' | 'ins' }

/** Word-level difference between two texts: what stayed, what was removed, what was added, in reading order.
 * Whitespace stays attached to the word before it, so joining every part's text rebuilds either side. */
export function wordDiff(before: string, after: string): DiffPart[] {
  const a = before.match(/\S+\s*/g) ?? [];
  const b = after.match(/\S+\s*/g) ?? [];
  const key = (w: string) => w.trim();
  // Longest common subsequence over words; texts here are a sentence or two, so the table stays small.
  const L = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i--)
    for (let j = b.length - 1; j >= 0; j--)
      L[i][j] = key(a[i]) === key(b[j]) ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  const out: DiffPart[] = [];
  const push = (text: string, kind: DiffPart['kind']) => {
    const last = out[out.length - 1];
    if (last && last.kind === kind) last.text += text;
    else out.push({ text, kind });
  };
  let i = 0, j = 0;
  while (i < a.length && j < b.length) {
    if (key(a[i]) === key(b[j])) { push(b[j], 'same'); i++; j++; }
    else if (L[i + 1][j] >= L[i][j + 1]) push(a[i++], 'del');
    else push(b[j++], 'ins');
  }
  while (i < a.length) push(a[i++], 'del');
  while (j < b.length) push(b[j++], 'ins');
  return out;
}

/** A field of a change as a person reads it: category codes become their names, lists are joined. */
export function fieldValue(field: string, v: unknown): string {
  if (field === 'category' && typeof v === 'string') return CATEGORY_NAMES[v as keyof typeof CATEGORY_NAMES] ?? v;
  if (Array.isArray(v)) return v.length ? v.join(', ') : 'none';
  if (v === '' || v === null || v === undefined) return 'empty';
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}

/** A field's name in words: "citation_ids" -> "Citations". */
export function fieldName(field: string): string {
  const names: Record<string, string> = { citation_ids: 'Citations', text: 'Text', category: 'Category', flags: 'Flags', note: 'Note' };
  return names[field] ?? (field[0].toUpperCase() + field.slice(1)).replace(/_/g, ' ');
}
