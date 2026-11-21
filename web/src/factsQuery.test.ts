import { describe, expect, it } from 'vitest';
import { emptyFilters, factsListQuery, listEntries, paginate, pct } from './factsQuery';
import type { Fact } from './types';

const fact = (id: string, over: Partial<Fact> = {}) =>
  ({ fact_id: id, text: `text ${id}`, citations: [{ page_label: '3' }], ...over }) as unknown as Fact;

describe('factsListQuery', () => {
  it('sends only the run for the default filters', () => {
    expect(factsListQuery('a/b', emptyFilters())).toBe('run=a%2Fb');
  });
  it('joins lists with commas and sends every set filter', () => {
    const f = {
      ...emptyFilters(), q: ' due date ', categories: ['D', 'S'], statuses: ['needs_review' as const], flags: ['risk' as const, 'mandatory' as const],
      pageFrom: 2, pageTo: 9, view: 'Bid' as const, splitOnly: true, edited: true, includeDeleted: true,
    };
    const p = new URLSearchParams(factsListQuery('r', f));
    expect(Object.fromEntries(p)).toEqual({
      run: 'r', q: 'due date', categories: 'D,S', statuses: 'needs_review', flags: 'risk,mandatory', page_from: '2', page_to: '9',
      view: 'Bid', split_only: '1', edited: '1', include_deleted: '1',
    });
  });
  it('treats all statuses as no filter', () => {
    expect(new URLSearchParams(factsListQuery('r', emptyFilters())).has('statuses')).toBe(false);
  });
});

describe('listEntries and paginate', () => {
  const facts = [fact('a'), fact('b', { group_title: 'Insurance' }), fact('c', { citations: [{ page_label: '4' } as never] })];
  it('shows a point stated in several places once, with its count', () => {
    const e = listEntries([{ kind: 'same', fact_ids: ['a', 'c'] }], facts);
    expect(e).toHaveLength(1);
    expect(e[0].stated).toBe(2);
    expect(e[0].pages).toBe('3; 4');
  });
  it('titles a list by its group title and skips missing facts', () => {
    const e = listEntries([{ kind: 'list', fact_ids: ['b', 'zz'] }, { kind: 'fact', fact_ids: ['zz'] }], facts);
    expect(e).toHaveLength(1);
    expect(e[0].title).toBe('Insurance');
    expect(e[0].facts).toHaveLength(1);
  });
  it('pages by items and clamps the page', () => {
    const xs = Array.from({ length: 31 }, (_, i) => i);
    expect(paginate(xs, 15, 1).slice).toHaveLength(15);
    expect(paginate(xs, 15, 3).slice).toEqual([30]);
    expect(paginate(xs, 15, 9)).toMatchObject({ page: 3, pages: 3 });
    expect(paginate([], 15, 1)).toMatchObject({ page: 1, pages: 1, slice: [] });
  });
});

describe('pct', () => {
  it('formats a share and tolerates null', () => {
    expect(pct(0.5)).toBe('50%');
    expect(pct(null)).toBe('-');
  });
});
