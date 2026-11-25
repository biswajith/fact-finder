// The deal graph as make_durham_graph.py writes it, and what the page works out from it.
// No model calls: everything here is plain lookups over the JSON.

export type FieldStatus = 'none' | 'auto_resolved' | 'needs_review' | 'decided' | 'tentative' | 'expired';
export type Review = 'needs_review' | 'settled' | 'not_final' | null;

export interface Competing { value: string; facts: string[] }
export interface Field { name: string; value: string; facts: string[]; status: FieldStatus; reason: string; competing: Competing[] }
export interface ListField { name: string; items: { value: string; facts: string[] }[] }
export interface GNode {
  id: string; type: string; label: string; sub: string; facts: string[];
  fields: Field[]; lists: ListField[]; status: 'live' | 'tentative' | 'removed'; note: string;
}
export interface GLink { from: string; edge: string; to: string; facts: string[]; status: string }
export interface Fact {
  text: string; category: string; flags: string[]; doc: number; step: number;
  page: string; section: string; quote: string; speaker: string; used: boolean;
}
export interface Doc { no: number; step: number; name: string; file: string; playbook: string; issued: string | null }
export interface LensRow { row: string; text: string; nodes: string[] }
export interface Lens { key: string; title: string; icon: string; rows: LensRow[] }
export interface TypeDef { name: string; color: string; shape: string }
export interface Graph {
  bid: { id: string; name: string };
  documents: Doc[]; types: Record<string, TypeDef>;
  nodes: GNode[]; links: GLink[]; facts: Record<string, Fact>; lenses: Lens[];
}

/** First document step at which any of these facts exists (Infinity when none do). */
export function firstStep(g: Graph, ids: string[]): number {
  let s = Infinity;
  for (const id of ids) s = Math.min(s, g.facts[id]?.step ?? Infinity);
  return s;
}

export function allFacts(n: GNode): string[] {
  return [
    ...n.facts,
    ...n.fields.flatMap((f) => [...f.facts, ...f.competing.flatMap((c) => c.facts)]),
    ...n.lists.flatMap((l) => l.items.flatMap((i) => i.facts)),
  ];
}

export const nodeStep = (g: Graph, n: GNode) => firstStep(g, allFacts(n));

/** A field as it stood after document `step`: the value, and whether its disagreement had appeared yet. */
export function fieldAt(g: Graph, f: Field, step: number): { value: string; status: FieldStatus; competing: Competing[] } | null {
  const own = firstStep(g, f.facts);
  const rivals = f.competing.filter((c) => firstStep(g, c.facts) <= step);
  if (own > step) {
    if (rivals.length === 0) return null;
    return { value: rivals[0].value, status: 'none', competing: [] };
  }
  const status = f.competing.length > 0 && rivals.length === 0 && (f.status === 'auto_resolved' || f.status === 'decided')
    ? 'none' : f.status;
  return { value: f.value, status, competing: rivals };
}

export function nodeReview(n: GNode): Review {
  const st = n.fields.map((f) => f.status);
  if (st.includes('needs_review')) return 'needs_review';
  if (n.status === 'tentative' || st.includes('tentative') || st.includes('expired')) return 'not_final';
  if (st.includes('auto_resolved') || st.includes('decided')) return 'settled';
  return null;
}

export const REVIEW_TEXT: Record<Exclude<Review, null>, string> = {
  needs_review: 'Needs a person',
  settled: 'Settled by ranking',
  not_final: 'Not final',
};

export const STATUS_TEXT: Record<FieldStatus, string> = {
  none: 'Agreed',
  auto_resolved: 'Settled by rank',
  needs_review: 'Needs a person',
  decided: 'Decided',
  tentative: 'Not final',
  expired: 'Expired',
};

export function sourceLabel(g: Graph, id: string): string {
  const f = g.facts[id];
  if (!f) return id;
  const doc = g.documents.find((d) => d.no === f.doc);
  const where = f.page && f.page !== '0' ? `p${f.page}` : f.section ? f.section.slice(0, 18) : '';
  return [doc?.name ?? `Doc ${f.doc}`, where].filter(Boolean).join(' · ');
}

// ---------------------------------------------------------------- asking the graph
export interface Hit { kind: 'row' | 'lens' | 'node' | 'fact'; score: number; label: string; detail: string; lens?: string; row?: number; node?: string; fact?: string }

const STOP = new Set('a an the of to and or for in on at is are was be by with what who when how do does our we us i me show tell about which where'.split(' '));
const words = (s: string) => s.toLowerCase().replace(/[^a-z0-9$.%]+/g, ' ').split(' ').filter((w) => w.length > 1 && !STOP.has(w));

/** Synonyms a bid manager types that the row names do not use. */
const ALIASES: Record<string, string[]> = {
  deadline: ['due', 'date', 'dates'], due: ['deadline'], when: ['date', 'dates'], deadlines: ['due', 'dates'],
  decides: ['decide', 'who', 'award'], decision: ['decide', 'award'], boss: ['decide'], stakeholders: ['people', 'influence'],
  money: ['price', 'pricing', 'budget'], cost: ['price', 'pricing'], budget: ['price', 'estimated'],
  insurance: ['insurance', 'liability'], risk: ['risks'], todo: ['actions'], tasks: ['actions'],
  competitors: ['competition'], competition: ['competitor'], rivals: ['competition'], contacts: ['contact'],
  disqualify: ['rejected'], eligible: ['who', 'may', 'bid'], references: ['experience', 'reference'],
  questions: ['clarifications', 'unclear'], scoring: ['criteria', 'method'], score: ['criteria'],
};

function expand(q: string): string[] {
  const base = words(q);
  return [...new Set(base.flatMap((w) => [w, ...(ALIASES[w] ?? [])]))];
}

function overlap(qw: string[], text: string): number {
  const tw = new Set(words(text));
  let s = 0;
  for (const w of qw) {
    if (tw.has(w)) s += 1;
    else if ([...tw].some((t) => t.startsWith(w) || (w.length > 4 && w.startsWith(t)))) s += 0.6;
  }
  return s;
}

export function ask(g: Graph, q: string, limit = 9): Hit[] {
  const qw = expand(q);
  if (qw.length === 0) return [];
  const hits: Hit[] = [];
  for (const lens of g.lenses) {
    const ls = overlap(qw, lens.title) * 1.4;
    if (ls > 0) hits.push({ kind: 'lens', score: ls + 0.5, label: lens.title, detail: `${lens.rows.length} rows as a graph`, lens: lens.key });
    lens.rows.forEach((r, i) => {
      const s = overlap(qw, r.row) * 2 + overlap(qw, r.text) * 0.7 + ls * 0.3;
      if (s > 0.6) hits.push({ kind: 'row', score: s, label: `${lens.title} › ${r.row}`, detail: r.text, lens: lens.key, row: i });
    });
  }
  for (const n of g.nodes) {
    const s = overlap(qw, n.label) * 2.2 + overlap(qw, n.sub) * 0.6
      + overlap(qw, n.fields.map((f) => `${f.name} ${f.value}`).join(' ')) * 0.35;
    if (s > 0.8) hits.push({ kind: 'node', score: s, label: n.label, detail: `${g.types[n.type]?.name ?? n.type} · ${n.sub}`, node: n.id });
  }
  for (const [id, f] of Object.entries(g.facts)) {
    const s = overlap(qw, f.text) * 0.45;
    if (s > 0.9) hits.push({ kind: 'fact', score: s, label: f.text, detail: sourceLabel(g, id), fact: id });
  }
  hits.sort((a, b) => b.score - a.score);
  // Keep the list varied: at most 4 of a kind.
  const seen: Record<string, number> = {};
  return hits.filter((h) => (seen[h.kind] = (seen[h.kind] ?? 0) + 1) <= 4).slice(0, limit);
}

export function nodesOfFact(g: Graph, factId: string): string[] {
  return g.nodes.filter((n) => allFacts(n).includes(factId)).map((n) => n.id);
}
