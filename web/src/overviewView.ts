import type { Conflict, Fact, ViewName } from './types';
import { CATEGORY_CODES } from './types';

/** Categories the After award view lists first, in this order; any other category follows. */
const AWARD_FIRST = ['C', 'R', 'D'];

export interface CategoryGroup { code: string; facts: Fact[] }

/** Facts grouped by category: Contract, Requirements, Dates, then the rest in the usual order. Empty groups are left out. */
export function groupByCategory(facts: Fact[]): CategoryGroup[] {
  const by = new Map<string, Fact[]>();
  for (const f of facts) by.set(f.category, [...(by.get(f.category) ?? []), f]);
  const rank = (c: string) => {
    const i = AWARD_FIRST.indexOf(c);
    if (i >= 0) return i;
    const j = (CATEGORY_CODES as readonly string[]).indexOf(c);
    return AWARD_FIRST.length + (j >= 0 ? j : CATEGORY_CODES.length);
  };
  return [...by.keys()]
    .sort((a, b) => rank(a) - rank(b) || a.localeCompare(b))
    .map((code) => ({ code, facts: by.get(code)! }));
}

/**
 * Open conflicts that matter in a view: under All, every open one; under Bid and After award,
 * those with at least one fact in `viewFactIds`. While that set is unknown (not loaded), all open ones.
 */
export function openConflictCount(conflicts: Conflict[], view: ViewName, viewFactIds: ReadonlySet<string> | null): number {
  const open = conflicts.filter((c) => c.status === 'open');
  if (view === 'All' || viewFactIds === null) return open.length;
  return open.filter((c) => c.fact_ids.some((id) => viewFactIds.has(id))).length;
}
