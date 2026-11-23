import { describe, expect, it } from 'vitest';
import { fieldName, fieldValue, wordDiff } from './changesView';

describe('wordDiff', () => {
  it('marks only the words that changed', () => {
    const d = wordDiff('Proposals are due May 24, 2024 at 2:00 pm ET.', 'Proposals are due May 31, 2024 at 2:00 pm ET.');
    expect(d).toEqual([
      { text: 'Proposals are due May ', kind: 'same' },
      { text: '24, ', kind: 'del' },
      { text: '31, ', kind: 'ins' },
      { text: '2024 at 2:00 pm ET.', kind: 'same' },
    ]);
  });

  it('rebuilds both sides from its parts', () => {
    const a = 'The vendor must host the system.';
    const b = 'The vendor may host the system in the cloud.';
    const d = wordDiff(a, b);
    expect(d.filter((p) => p.kind !== 'ins').map((p) => p.text).join('')).toBe(a);
    expect(d.filter((p) => p.kind !== 'del').map((p) => p.text).join('')).toBe(b);
  });

  it('handles empty sides', () => {
    expect(wordDiff('', 'New text')).toEqual([{ text: 'New text', kind: 'ins' }]);
    expect(wordDiff('Old', '')).toEqual([{ text: 'Old', kind: 'del' }]);
  });
});

describe('fields in words', () => {
  it('names categories and fields', () => {
    expect(fieldValue('category', 'B')).toBe('Buyer information');
    expect(fieldValue('flags', [])).toBe('none');
    expect(fieldName('citation_ids')).toBe('Citations');
  });
});
