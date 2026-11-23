import { describe, expect, it } from 'vitest';
import { canConfirm, extractCount, levelLabel, missingWords, rowsInOrder, stepsByDocument } from './bid';
import type { BidDocument, BidPlan, JobStep } from './types';

const doc = (no: number, over: Partial<BidDocument> = {}) =>
  ({ no, doc_id: `D${no}`, file_name: `f${no}.pdf`, speakers: [], missing: [], ...over }) as unknown as BidDocument;
const step = (doc_no: number, s: string, status: JobStep['status'] = 'done'): JobStep => ({ doc_no, step: s, status, detail: '' });

describe('levelLabel', () => {
  it('words the three levels and tolerates a missing playbook', () => {
    expect(levelLabel({ level: '1' })).toBe('Level 1 · buyer document');
    expect(levelLabel({ level: 'by speaker' })).toBe('Level 2/3 · by speaker');
    expect(levelLabel({ level: '4' })).toBe('Level 4 · deal notes');
    expect(levelLabel(undefined)).toBe('');
  });
});

describe('missingWords', () => {
  it('turns the server reasons into one sentence', () => {
    expect(missingWords([])).toBe('');
    expect(missingWords(['issue date missing', 'speakers not confirmed'])).toBe('To do: add the issue date; confirm the speakers.');
    expect(missingWords(['something new'])).toBe('To do: something new.');
  });
});

describe('rowsInOrder', () => {
  it('follows the issue order, not the upload order, and keeps unnamed documents last', () => {
    const documents = [doc(1), doc(2), doc(3), doc(4)];
    expect(rowsInOrder({ documents, order: ['D3', 'D1', 'D2'] }).map((d) => d.no)).toEqual([3, 1, 2, 4]);
  });
  it('lists a document once', () => {
    expect(rowsInOrder({ documents: [doc(1)], order: ['D1', 'D1', 'gone'] })).toHaveLength(1);
  });
});

describe('canConfirm', () => {
  const none = { issue_number: null, issue_date: null, previous: null };
  it('needs a type', () => expect(canConfirm(none, undefined)).toBe(false));
  it('asks nothing more of a base document', () => expect(canConfirm(none, { name: 'rfp', role: 'base' })).toBe(true));
  it('asks an addendum for a number and a date', () => {
    const pb = { name: 'change-addendum', role: 'change' as const };
    expect(canConfirm({ ...none, issue_date: '2026-08-01' }, pb)).toBe(false);
    expect(canConfirm({ ...none, issue_number: 1 }, pb)).toBe(false);
    expect(canConfirm({ ...none, issue_number: 1, issue_date: '2026-08-01' }, pb)).toBe(true);
  });
  it('asks a call or notes for a date, and a reissue for the document it replaces', () => {
    expect(canConfirm(none, { name: 'deal-notes', role: 'context' })).toBe(false);
    expect(canConfirm({ ...none, issue_date: '2026-08-01' }, { name: 'call-transcript', role: 'context' })).toBe(true);
    expect(canConfirm(none, { name: 'reissued-rfp', role: 'base' })).toBe(false);
    expect(canConfirm({ ...none, previous: 'D1' }, { name: 'reissued-rfp', role: 'base' })).toBe(true);
  });
});

describe('stepsByDocument', () => {
  const docs = [doc(2), doc(1)];
  it('groups by document in the given order, then the whole bid', () => {
    const steps = [step(1, 'cut'), step(2, 'cut'), step(0, 'plan'), step(2, 'extract', 'running'), step(0, 'group', 'running')];
    const g = stepsByDocument(steps, docs);
    expect(g.map((x) => x.title)).toEqual(['d2 f2.pdf', 'd1 f1.pdf', 'Whole bid']);
    expect(g[0].steps.map((s) => s.step)).toEqual(['cut', 'extract']);
    expect(g[2].steps.map((s) => s.step)).toEqual(['group']);
  });
  it('keeps the last report of a step', () => {
    const g = stepsByDocument([step(1, 'relate', 'running'), step(1, 'relate', 'done')], docs);
    expect(g[0].steps).toHaveLength(1);
    expect(g[0].steps[0].status).toBe('done');
  });
  it('is empty before the first step', () => expect(stepsByDocument([], docs)).toEqual([]));
});

describe('extractCount', () => {
  it('counts the planned documents with nothing missing', () => {
    const plan = { documents: [{ missing: [] }, { missing: ['issue date missing'] }, { missing: [] }] } as unknown as BidPlan;
    expect(extractCount(plan)).toBe(2);
    expect(extractCount(null)).toBe(0);
  });
});
