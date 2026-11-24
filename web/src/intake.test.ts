import { describe, expect, it } from 'vitest';
import {
  agoLabel, callsOf, canAccept, changedSides, customersOf, dateLabel, docLight, docRunState, draftOf, formatOf, gapsOf, inFilter, isAccepted, jobProgress,
  openSpeakers, peopleOf, runningNow, speakersBody, stageOf, suggestedBy, waitsForSpeakers, withSuggestions, wizard,
} from './intake';
import type { Bid, BidDocument, BidPlaybook, BidSpeaker, ExtractJob, JobStep } from './types';

const PLAYBOOKS = [
  { name: 'rfp', role: 'base', spoken: false, level: '1', visibility: 'external' },
  { name: 'reissued-rfp', role: 'base', spoken: false, level: '1', visibility: 'external' },
  { name: 'change-addendum', role: 'change', spoken: false, level: '1', visibility: 'external' },
  { name: 'call-transcript', role: 'context', spoken: true, level: 'by speaker', visibility: 'internal' },
  { name: 'deal-notes', role: 'context', spoken: false, level: '4', visibility: 'internal' },
] as unknown as BidPlaybook[];
const pb = (name: string) => PLAYBOOKS.find((p) => p.name === name);

const doc = (no: number, over: Partial<BidDocument> = {}) => ({
  no, doc_id: `D${no}`, file_name: `f${no}.pdf`, playbook: 'rfp', issue_number: null, issue_date: null, previous: null, confirmed: false, run: '', status: 'uploaded',
  speakers: [], speakers_confirmed: false, missing: ['type not confirmed'], error: '', pages: 1,
  proposed: { playbook: 'rfp', issue_number: null, issue_date: null, by: 'model', checked: true },
  ...over,
}) as unknown as BidDocument;
const bidOf = (docs: BidDocument[]) => ({ documents: docs, playbooks: PLAYBOOKS, team: [], order: [] }) as unknown as Bid;
const step = (doc_no: number, s: string, status: JobStep['status'] = 'done'): JobStep => ({ doc_no, step: s, status, detail: '' });
const speaker = (id: string, over: Partial<BidSpeaker> = {}) => ({ id, name: id, side: '', proposed: 'unknown', why: 'none', ...over }) as unknown as BidSpeaker;

describe('files', () => {
  it('takes the types the server takes', () => {
    expect(['a.PDF', 'a.docx', 'a.json', 'a.txt', 'a.md', 'a.csv', 'a.xlsx'].every(isAccepted)).toBe(true);
    expect(['a.exe', 'a.vtt', 'a'].some(isAccepted)).toBe(false);
  });
  it('tells the format from the name', () => {
    expect(['a.pdf', 'a.docx', 'a.csv', 'a.xlsx', 'a.json', 'a.md'].map(formatOf)).toEqual(['pdf', 'word', 'sheet', 'sheet', 'json', 'text']);
  });
});

describe('the bids list', () => {
  it('is Ready with a fact list, Reading while its job runs, else Intake', () => {
    expect(stageOf({ bid_id: 'a', run: '_bids/a' }, null)).toBe('Ready');
    expect(stageOf({ bid_id: 'a', run: '' }, null)).toBe('Intake');
    expect(stageOf({ bid_id: 'a', run: '_bids/a' }, 'a')).toBe('Reading');
    expect(stageOf({ bid_id: 'a', run: '' }, 'b')).toBe('Intake');
  });
  it('words a date and how long ago', () => {
    expect(dateLabel('2026-09-02')).toBe('2 Sep 2026');
    expect([dateLabel(null), dateLabel('soon')]).toEqual(['', 'soon']);
    const now = Date.parse('2026-08-20T12:00:00Z');
    expect(agoLabel('2026-08-20T11:59:30Z', now)).toBe('just now');
    expect(agoLabel('2026-08-20T11:55:00Z', now)).toBe('5 minutes ago');
    expect(agoLabel('2026-08-20T11:00:00Z', now)).toBe('1 hour ago');
    expect(agoLabel('2026-08-18T12:00:00Z', now)).toBe('2 days ago');
    expect(agoLabel(Date.parse('2026-08-20T11:00:00Z') / 1000, now)).toBe('1 hour ago');
    expect(agoLabel('', now)).toBe('');
  });
  it('suggests each customer and each person once', () => {
    expect(customersOf([{ customer: 'Ulster County' }, { customer: '' }, { customer: 'ulster county' }, { customer: 'Albany' }])).toEqual(['Ulster County', 'Albany']);
    expect(peopleOf([[{ name: 'Tom', role: 'Bid manager' }, { name: 'Ann' }], [{ name: 'tom', role: 'x' }, { name: 'Lee', role: 'Pricing' }]], ['ann']))
      .toEqual([{ name: 'Tom', role: 'Bid manager' }, { name: 'Lee', role: 'Pricing' }]);
  });
});

describe('a document', () => {
  it('lists what it still needs', () => {
    expect(gapsOf(doc(1), undefined)).toEqual([]);
    expect(gapsOf(doc(1), pb('rfp'))).toEqual([]);
    expect(gapsOf(doc(1), pb('change-addendum'))).toEqual(['issue date', 'issue number']);
    expect(gapsOf(doc(1, { issue_date: '2026-08-01', issue_number: 1 }), pb('change-addendum'))).toEqual([]);
    expect(gapsOf(doc(1), pb('deal-notes'))).toEqual(['issue date']);
    expect(gapsOf(doc(1), pb('reissued-rfp'))).toEqual(['earlier issue']);
  });
  it('has a status light for each state', () => {
    const light = (d: BidDocument) => docLight(d, pb(d.playbook));
    expect(light(doc(1))).toEqual({ tone: 'info', text: 'Ready to confirm' });
    expect(light(doc(1, { playbook: 'change-addendum' }))).toEqual({ tone: 'notice', text: 'Check: issue date' });
    expect(light(doc(1, { confirmed: true, status: 'confirmed' }))).toEqual({ tone: 'positive', text: 'Confirmed' });
    expect(light(doc(1, { confirmed: true, playbook: 'deal-notes' }))).toEqual({ tone: 'negative', text: 'Needs issue date' });
    expect(light(doc(1, { status: 'failed', confirmed: true }))).toEqual({ tone: 'negative', text: 'Could not read' });
    expect(light(doc(1, { status: 'extracting', confirmed: true }))).toEqual({ tone: 'info', text: 'Reading' });
    expect(light(doc(1, { status: 'extracted', confirmed: true, run: 'x' }))).toEqual({ tone: 'positive', text: 'Read' });
  });
  it('says who suggested the type', () => {
    expect(suggestedBy(doc(1))).toBe('Suggested by the model');
    expect(suggestedBy(doc(1, { proposed: { playbook: 'rfp', by: 'rules' } as BidDocument['proposed'] }))).toBe('Suggested by rules');
    expect(suggestedBy(doc(1, { playbook: 'deal-notes' }))).toBe('Changed by you');
  });
  it('can be accepted when editable and complete', () => {
    expect(canAccept(doc(1), pb('rfp'))).toBe(true);
    expect(canAccept(doc(1, { confirmed: true }), pb('rfp'))).toBe(false);
    expect(canAccept(doc(1, { playbook: 'change-addendum' }), pb('change-addendum'))).toBe(false);
    expect(canAccept(doc(1), undefined)).toBe(false);
  });
  it('falls into the filters', () => {
    const review = doc(1);
    const open = doc(2, { playbook: 'deal-notes' });
    const done = doc(3, { confirmed: true });
    const failed = doc(4, { confirmed: true, status: 'failed' });
    const f = (name: Parameters<typeof inFilter>[0], d: BidDocument) => inFilter(name, d, pb(d.playbook));
    expect([review, open, done, failed].map((d) => f('review', d))).toEqual([true, true, false, false]);
    expect([review, open, done, failed].map((d) => f('confirmed', d))).toEqual([false, false, true, true]);
    expect([review, open, done, failed].map((d) => f('problems', d))).toEqual([false, true, false, true]);
    expect(f('all', failed)).toBe(true);
  });
  it('waits for speakers by the server words', () => {
    expect(waitsForSpeakers({ missing: ['speakers not confirmed'] })).toBe(true);
    expect(waitsForSpeakers({ missing: ['issue date missing'] })).toBe(false);
  });
});

describe('speakers', () => {
  const people = [speaker('a', { proposed: 'buyer' }), speaker('b', { proposed: 'ours', side: 'ours' }), speaker('c', { proposed: 'unknown' }), speaker('d', { side: 'unknown' })];
  it('starts from the sides already set; unknown is no side', () => {
    expect(draftOf(people)).toEqual({ a: { side: '', acts_for: '' }, b: { side: 'ours', acts_for: '' }, c: { side: '', acts_for: '' }, d: { side: '', acts_for: '' } });
  });
  it('uses the suggestions only where a side is open and one was made', () => {
    const d = withSuggestions(people, draftOf(people));
    expect(d.a.side).toBe('buyer');
    expect(d.c.side).toBe('');
    expect(openSpeakers(people, d).map((s) => s.id)).toEqual(['c', 'd']);
  });
  it('counts the sides the reader changed and builds the confirm body', () => {
    const d = { ...withSuggestions(people, draftOf(people)), a: { side: 'other' as const, acts_for: 'buyer' }, c: { side: 'buyer' as const, acts_for: 'ours' } };
    expect(changedSides(people, d)).toBe(1);
    const body = speakersBody(people.slice(0, 3), d);
    expect(body[0]).toEqual({ id: 'a', name: 'a', side: 'other', acts_for: 'buyer' });
    expect(body[2].acts_for).toBe('');
  });
});

describe('the wizard', () => {
  const base = { step: 'details' as const, bid: null, name: '', customer: '', due: null, pending: 0, job: null };
  const confirmedRfp = doc(1, { confirmed: true, status: 'confirmed', missing: [] });
  const call = (over: Partial<BidDocument> = {}) => doc(2, { playbook: 'call-transcript', issue_date: '2026-08-12', confirmed: true, status: 'confirmed', missing: ['speakers not confirmed'], speakers: [speaker('s')], ...over });

  it('needs a name to leave the details and nothing else', () => {
    expect(wizard(base).canNext).toBe(false);
    expect(wizard(base).blocker).toMatch(/name/);
    const w = wizard({ ...base, name: 'Ulster' });
    expect(w.canNext).toBe(true);
    expect(w.steps.map((s) => s.enabled)).toEqual([true, true, false, false, false]);
  });
  it('holds the reader at the documents until one is confirmed, with nothing left to upload', () => {
    const b = bidOf([doc(1)]);
    expect(wizard({ ...base, step: 'documents', bid: b, name: 'x' }).blocker).toMatch(/Confirm at least one/);
    expect(wizard({ ...base, step: 'documents', bid: bidOf([confirmedRfp]), name: 'x', pending: 1 }).blocker).toMatch(/Reading 1 document/);
    expect(wizard({ ...base, step: 'documents', bid: bidOf([confirmedRfp]), name: 'x' }).canNext).toBe(true);
  });
  it('mentions unconfirmed documents that are left out', () => {
    const w = wizard({ ...base, step: 'documents', bid: bidOf([confirmedRfp, doc(3)]), name: 'x' });
    expect(w.canNext).toBe(true);
    expect(w.summary).toMatch(/1 unconfirmed document is left out/);
  });
  it('waits for the speakers of a call that was read, not for one that could not be', () => {
    const open = bidOf([confirmedRfp, call()]);
    expect(callsOf(open)).toHaveLength(1);
    const at = wizard({ ...base, step: 'speakers', bid: open, name: 'x' });
    expect(at.canNext).toBe(false);
    expect(at.blocker).toMatch(/Confirm the speakers of the call/);
    expect(wizard({ ...base, step: 'speakers', bid: bidOf([confirmedRfp, call({ speakers_confirmed: true })]), name: 'x' }).canNext).toBe(true);
    const unread = bidOf([confirmedRfp, call({ missing: ['speakers not read yet'], speakers: [] })]);
    expect(wizard({ ...base, step: 'speakers', bid: unread, name: 'x' }).canNext).toBe(true);
  });
  it('skips the speakers when there is no call, and opens the run once started', () => {
    const b = bidOf([confirmedRfp]);
    const w = wizard({ ...base, step: 'review', bid: b, name: 'x' });
    expect(w.hasCalls).toBe(false);
    expect(w.steps[2].state).toBe('skipped');
    expect(w.steps[4].enabled).toBe(false);
    const running = { status: 'running' } as ExtractJob;
    const r = wizard({ ...base, step: 'run', bid: b, name: 'x', job: running });
    expect(r.steps[4]).toMatchObject({ enabled: true, sub: 'Running', state: 'current' });
    expect(wizard({ ...base, step: 'run', bid: b, name: 'x', job: { status: 'done' } as ExtractJob }).steps[4].sub).toBe('Finished');
  });
});

describe('a run', () => {
  it('finds where a document stands', () => {
    expect(docRunState([], 1)).toBe('waiting');
    expect(docRunState([step(1, 'cut', 'running')], 1)).toBe('running');
    expect(docRunState([step(1, 'cut'), step(1, 'save')], 1)).toBe('done');
    expect(docRunState([step(1, 'extract', 'reused')], 1)).toBe('done');
    expect(docRunState([step(1, 'extract', 'failed')], 1)).toBe('failed');
    expect(docRunState([step(1, 'cut', 'running'), step(1, 'cut', 'done')], 1)).toBe('running');
  });
  it('counts finished steps over four a document and three for the bid', () => {
    expect(jobProgress([], [1, 2])).toBe(0);
    expect(jobProgress([step(1, 'cut'), step(1, 'extract')], [1, 2])).toBeCloseTo(2 / 11);
    expect(jobProgress([step(1, 'save'), step(2, 'extract', 'reused'), step(0, 'group'), step(0, 'pairs'), step(0, 'build')], [1, 2])).toBe(1);
    expect(jobProgress([step(1, 'cut', 'running')], [1])).toBe(0);
    expect(jobProgress([], [])).toBe(0);
  });
  it('names the step that runs now', () => {
    const files = new Map([[2, 'call.json']]);
    expect(runningNow([step(2, 'extract', 'running')], files)).toBe('Label the units and build facts, d2 call.json');
    expect(runningNow([step(0, 'group', 'running')], files)).toBe('Group repeated points');
    expect(runningNow([step(1, 'cut')], files)).toBe('');
  });
});
