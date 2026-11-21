import { describe, expect, it } from 'vitest';
import { groupByCategory, openConflictCount } from './overviewView';
import type { Conflict, Fact } from './types';

const fact = (id: string, category: string) => ({ fact_id: id, category }) as unknown as Fact;
const conflict = (id: string, fact_ids: string[], status: 'open' | 'resolved' = 'open') => ({ id, fact_ids, status }) as unknown as Conflict;

describe('groupByCategory', () => {
  it('puts Contract, Requirements and Dates first, then the rest, skipping empty ones', () => {
    const g = groupByCategory([fact('1', 'S'), fact('2', 'D'), fact('3', 'R'), fact('4', 'C'), fact('5', 'R'), fact('6', 'G')]);
    expect(g.map((x) => x.code)).toEqual(['C', 'R', 'D', 'G', 'S']);
    expect(g[1].facts.map((f) => f.fact_id)).toEqual(['3', '5']);
  });
  it('keeps an unknown category last', () => {
    expect(groupByCategory([fact('1', 'Z'), fact('2', 'C')]).map((x) => x.code)).toEqual(['C', 'Z']);
  });
});

describe('openConflictCount', () => {
  const all = [conflict('a', ['f1', 'f2']), conflict('b', ['f3']), conflict('c', ['f1'], 'resolved')];
  it('counts every open conflict under All', () => expect(openConflictCount(all, 'All', new Set(['f1']))).toBe(2));
  it('counts only conflicts touching a fact in the view', () => {
    expect(openConflictCount(all, 'After award', new Set(['f2']))).toBe(1);
    expect(openConflictCount(all, 'Bid', new Set(['x']))).toBe(0);
  });
  it('falls back to all open ones while the view facts are not loaded', () => expect(openConflictCount(all, 'Bid', null)).toBe(2));
});
