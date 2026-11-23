// Pure helpers for the Facts tab: the filter query string and the grouping of the list.
import type { Fact, FactItem, FactsListFilters, FactStatus } from './types';

export const ALL_STATUSES: FactStatus[] = ['valid', 'needs_review', 'conflict'];
export const PAGE_SIZES = [60, 120, 240] as const;

export const emptyFilters = (): FactsListFilters => ({
  q: '', categories: [], statuses: [...ALL_STATUSES], flags: [], pageFrom: null, pageTo: null,
  view: 'All', splitOnly: false, edited: false, includeDeleted: false,
});

/**
 * Query string for GET /facts/list and /facts.csv. Parameters equal to "no filter" are left
 * out: all statuses, no categories or flags, the view All, no page range, switches off.
 * List values are comma-separated.
 */
export function factsListQuery(run: string, f: FactsListFilters): string {
  const s = new URLSearchParams();
  s.set('run', run);
  const q = f.q.trim();
  if (q) s.set('q', q);
  if (f.categories.length) s.set('categories', f.categories.join(','));
  const allStatuses = ALL_STATUSES.every((x) => f.statuses.includes(x));
  if (!allStatuses && f.statuses.length) s.set('statuses', f.statuses.join(','));
  if (f.flags.length) s.set('flags', f.flags.join(','));
  if (f.pageFrom !== null && f.pageTo !== null) {
    s.set('page_from', String(f.pageFrom));
    s.set('page_to', String(f.pageTo));
  }
  if (f.view !== 'All') s.set('view', f.view);
  if (f.splitOnly) s.set('split_only', '1');
  if (f.edited) s.set('edited', '1');
  if (f.includeDeleted) s.set('include_deleted', '1');
  return s.toString();
}

/** What the list draws for one server item. */
export interface ListEntry {
  kind: FactItem['kind'];
  facts: Fact[];
  first: Fact;
  /** "stated N times" for a point restated in several places. */
  stated: number;
  title: string;
  pages: string;
}

export function pagesOf(facts: Fact[]): string {
  const seen = new Set<string>();
  for (const f of facts) for (const c of f.citations) if (c.page_label) seen.add(c.page_label);
  return [...seen].join('; ');
}

/** Resolve the server's items against the loaded facts (by ID); items whose facts are missing are dropped. */
export function listEntries(items: FactItem[], byId: ReadonlyMap<string, Fact>): ListEntry[] {
  const out: ListEntry[] = [];
  for (const it of items) {
    const fs = it.fact_ids.map((id) => byId.get(id)).filter((f): f is Fact => !!f);
    if (fs.length === 0) continue;
    const first = fs[0];
    out.push({
      kind: it.kind, facts: fs, first,
      stated: it.kind === 'same' ? fs.length : 1,
      title: it.kind === 'list' ? first.group_title || first.text : first.text,
      pages: pagesOf(fs),
    });
  }
  return out;
}

/** One page of entries (1-based); paging counts items, not facts. */
export function paginate<T>(entries: T[], size: number, page: number): { slice: T[]; page: number; pages: number } {
  const pages = Math.max(1, Math.ceil(entries.length / size));
  const cur = Math.min(Math.max(1, page), pages);
  return { slice: entries.slice((cur - 1) * size, cur * size), page: cur, pages };
}

/** The most helpful percent for the comparison figures; "-" when there is none. */
export function pct(v: number | null | undefined): string {
  return typeof v === 'number' ? `${Math.round(v * 100)}%` : '-';
}
