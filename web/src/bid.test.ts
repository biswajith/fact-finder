import { describe, expect, it } from 'vitest';
import { extractCount, levelLabel, missingWords, playbookLabel, rowsInOrder, sideLabel } from './bid';
import type { BidDocument, BidPlan } from './types';

const doc = (no: number, over: Partial<BidDocument> = {}) =>
  ({ no, doc_id: `D${no}`, file_name: `f${no}.pdf`, speakers: [], missing: [], ...over }) as unknown as BidDocument;

describe('levelLabel', () => {
  it('words the three levels and tolerates a missing playbook', () => {
    expect(levelLabel({ level: '1' })).toBe('Level 1 · buyer document');
    expect(levelLabel({ level: 'by speaker' })).toBe('Level 2/3 · by speaker');
    expect(levelLabel({ level: '4' })).toBe('Level 4 · deal notes');
    expect(levelLabel(undefined)).toBe('');
  });
});

describe('playbookLabel', () => {
  it('names every playbook in words and leaves an unknown one as it is', () => {
    expect(['rfp', 'reissued-rfp', 'change-addendum', 'qa-addendum', 'fill-in-template', 'call-transcript', 'deal-notes'].map(playbookLabel)).toEqual([
      'RFP', 'Reissued RFP', 'Change addendum', 'Q&A addendum', 'Fill-in template', 'Call transcript', 'Deal notes',
    ]);
    expect(playbookLabel('something-new')).toBe('something-new');
    expect(playbookLabel(null)).toBe('');
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

describe('extractCount', () => {
  it('counts the planned documents with nothing missing', () => {
    const plan = { documents: [{ missing: [] }, { missing: ['issue date missing'] }, { missing: [] }] } as unknown as BidPlan;
    expect(extractCount(plan)).toBe(2);
    expect(extractCount(null)).toBe(0);
  });
});

import { fileSizeLabel, showPrecedence } from './bid';
import type { Bid } from './types';

describe('fileSizeLabel', () => {
  it('gives KB below a megabyte and MB with one decimal above', () => {
    expect(fileSizeLabel(512 * 1024)).toBe('512 KB');
    expect(fileSizeLabel(Math.round(1.4 * 1024 * 1024))).toBe('1.4 MB');
    expect(fileSizeLabel(10)).toBe('1 KB');
    expect(fileSizeLabel(0)).toBe('0 KB');
  });
});

const bidWith = (playbooks: string[]) =>
  ({
    documents: playbooks.map((p, i) => doc(i + 1, { playbook: p })),
    playbooks: [
      { name: 'rfp', level: '1' }, { name: 'change-addendum', level: '1' },
      { name: 'call-transcript', level: 'by speaker' }, { name: 'deal-notes', level: '4' },
    ],
  }) as unknown as Bid;

describe('showPrecedence', () => {
  it('shows precedence only with two or more level 1 documents', () => {
    expect(showPrecedence(bidWith(['rfp', 'call-transcript']))).toBe(false);
    expect(showPrecedence(bidWith(['rfp', 'change-addendum', 'deal-notes']))).toBe(true);
  });
});

describe('sideLabel', () => {
  it('words the three sides and leaves an undecided one empty', () => {
    expect(['buyer', 'ours', 'other'].map(sideLabel)).toEqual(['Buyer', 'Our side', 'Other party']);
    expect([sideLabel('unknown'), sideLabel(''), sideLabel(undefined)]).toEqual(['', '', '']);
  });
});
