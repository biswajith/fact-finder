import { describe, expect, it } from 'vitest';
import { bidDocs, citeLabel, citeTitle, describeEffect, internalOnly, levelChip, optionEffects, reasonWords, relationLines, replacedState } from './bidView';
import type { Citation, Fact, FactsDocument } from './types';

const doc = (no: number, file: string, has_pdf = true): FactsDocument => ({
  no, doc_id: `D${no}`, file_name: file, playbook: 'rfp', level: '1', visibility: 'external', issue_date: null, issue_number: null, has_pdf,
});
const docs = bidDocs([doc(1, 'call.json', false), doc(2, 'rfp.pdf')]);
const cite = (over: Partial<Citation>) => ({ id: 'p1.1', page: 4, page_label: '4', section: '', text: '', bbox: null, ...over }) as Citation;
const fact = (over: Partial<Fact>) => ({ fact_id: 'f1', flags: [], citations: [], ...over }) as unknown as Fact;

describe('bidDocs', () => {
  it('is a bid only when documents are listed', () => {
    expect(bidDocs(undefined).inBid).toBe(false);
    expect(bidDocs([]).inBid).toBe(false);
    expect(docs.inBid).toBe(true);
  });
});

describe('citations', () => {
  it('reads d<no> and the page', () => {
    const c = cite({ doc_id: 'D2', doc_no: 2 });
    expect(citeLabel(c, docs)).toBe('d2 · p.4');
    expect(citeTitle(c, docs)).toBe('rfp.pdf');
  });
  it('shows the time and the speaker of a transcript citation', () => {
    expect(citeLabel(cite({ doc_id: 'D1', doc_no: 1, page_label: '00:04:12', speaker: 'Dana Whitcomb' }), docs)).toBe('d1 · 00:04:12 · Dana Whitcomb');
  });
  it('finds the document by its ID when the number is missing', () => {
    expect(citeLabel(cite({ doc_id: 'D2' }), docs)).toBe('d2 · p.4');
  });
  it('knows a fact that only cites internal sources', () => {
    const i = cite({ visibility: 'internal' });
    expect(internalOnly(fact({ citations: [i] }))).toBe(true);
    expect(internalOnly(fact({ citations: [i, cite({ visibility: 'external' })] }))).toBe(false);
    expect(internalOnly(fact({ citations: [] }))).toBe(false);
  });
});

describe('levels', () => {
  it('names the four levels', () => {
    expect([1, 2, 3, 4].map(levelChip)).toEqual(['L1 · Buyer document', 'L2 · Buyer on a call', 'L3 · Our side on a call', 'L4 · Deal notes']);
    expect(levelChip(0)).toBe('');
    expect(levelChip(undefined)).toBe('');
  });
});

describe('replacedState', () => {
  it('is null for a current fact', () => expect(replacedState(fact({}))).toBeNull());
  it('names the governing fact', () => expect(replacedState(fact({ flags: ['replaced'], replaced_by: 'f9' }))).toEqual({ kind: 'by', id: 'f9' }));
  it('says removed when a REMOVES relation points at it', () => {
    const r = { id: 'r_1', kind: 'REMOVES' as const, from: { doc_id: 'D2', unit: 'p1.1', fact_id: 'x' }, to: { doc_id: 'D1', unit: 'p1.2', fact_id: 'f1' }, rejected: false };
    expect(replacedState(fact({ flags: ['replaced'], replaced_by: '', relations: [r] }))).toEqual({ kind: 'removed' });
    expect(replacedState(fact({ flags: ['replaced'], replaced_by: '' }))).toEqual({ kind: 'plain' });
  });
});

describe('relationLines', () => {
  const r = (kind: 'REPLACES' | 'CONFIRMS' | 'DISAGREES', from: string, to: string, rejected = false) =>
    ({ id: `r_${kind}`, kind, from: { doc_id: 'A', unit: 'p1.1', fact_id: from }, to: { doc_id: 'B', unit: 'p2.2', fact_id: to }, rejected });
  it('words a relation from the point of view of the fact', () => {
    const f = fact({ fact_id: 'f1', relations: [r('REPLACES', 'f1', 'f2'), r('CONFIRMS', 'f3', 'f1')] });
    expect(relationLines(f).map((l) => [l.words, l.otherFactId])).toEqual([['Replaces', 'f2'], ['Confirmed by', 'f3']]);
  });
  it('skips a rejected relation and shows a relation once', () => {
    const f = fact({ fact_id: 'f1', relations: [r('DISAGREES', 'f1', 'f2', true), r('REPLACES', 'f1', 'f2'), r('REPLACES', 'f1', 'f2')] });
    expect(relationLines(f)).toHaveLength(1);
  });
  it('keeps the unit when no fact stands at the other end', () => {
    const l = relationLines(fact({ fact_id: 'f1', relations: [r('REPLACES', 'f1', '')] }))[0];
    expect([l.otherFactId, l.otherDocId, l.otherUnit]).toEqual(['', 'B', 'p2.2']);
  });
});

describe('conflicts', () => {
  const ref = (id: string) => `fact ${id}`;
  it('says the reason in words', () => {
    expect(reasonWords('levels disagree')).toBe('Sources at different levels disagree');
    expect(reasonWords('issued together')).toBe('Two documents issued together disagree');
    expect(reasonWords('something new')).toBe('something new');
    expect(reasonWords(undefined)).toBe('');
  });
  it('says what a change does', () => {
    expect(describeEffect({ op: 'edit', fact_id: 'a', fields: { flags: ['replaced'] }, add_flag: 'replaced' }, ref)).toBe('Marks fact a replaced');
    expect(describeEffect({ op: 'edit', fact_id: 'a', fields: { text: 'New value' } }, ref)).toBe('Changes the text to "New value"');
    expect(describeEffect({ op: 'edit', fact_id: 'a', fields: { flags: ['unclear'] }, add_flag: 'unclear' }, ref)).toBe('Adds the flag "unclear" to fact a');
    expect(describeEffect({ op: 'delete', fact_id: 'a' }, ref)).toBe('Deletes fact a');
  });
  it('says "No change" for an option that changes nothing', () => {
    expect(optionEffects({ label: 'Ask the buyer', text: '', changes: [], question: true }, ref)).toEqual(['No change']);
  });
});
