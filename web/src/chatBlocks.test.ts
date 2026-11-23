import { describe, expect, it } from 'vitest';
import { splitBlocks } from './chatBlocks';

const A = 'f_0123456789';
const B = 'f_abcdef0123';
const U = 'u_00ff00ff00';

describe('splitBlocks', () => {
  it('returns plain text as one part', () => {
    expect(splitBlocks('Just words.\n\nMore.')).toEqual([{ kind: 'text', text: 'Just words.\n\nMore.' }]);
    expect(splitBlocks('')).toEqual([]);
  });

  it('turns a source token alone on its line into a block', () => {
    expect(splitBlocks(`It is on page 4.\n[[source:${A}]]\nNext.`)).toEqual([
      { kind: 'text', text: 'It is on page 4.' },
      { kind: 'source', factId: A },
      { kind: 'text', text: 'Next.' },
    ]);
  });

  it('turns a timeline token into a block, accepting user-added ids and spaces around it', () => {
    expect(splitBlocks(`Dates:\n  [[timeline:${A},${U},${B}]]  `)).toEqual([
      { kind: 'text', text: 'Dates:' },
      { kind: 'timeline', factIds: [A, U, B] },
    ]);
  });

  it('gives a token written inside a sentence a line of its own', () => {
    expect(splitBlocks(`See it here. [[source:${A}]]`)).toEqual([
      { kind: 'text', text: 'See it here.' },
      { kind: 'source', factId: A },
    ]);
  });

  it('keeps malformed tokens as text', () => {
    const t = ['[[source:f_12]]', `[[source:${A},${B}]]`, `[[timeline:${A}]]`, `[[timeline:${A},]]`, `[[timeline:${A},${B}`, '[[chart:1]]', `[source:${A}]`].join('\n');
    expect(splitBlocks(t)).toEqual([{ kind: 'text', text: t }]);
  });

  it('allows at most 12 ids in a timeline', () => {
    const ids = Array.from({ length: 13 }, (_, i) => `f_${String(i).padStart(10, '0')}`);
    expect(splitBlocks(`[[timeline:${ids.join(',')}]]`)[0].kind).toBe('text');
    expect(splitBlocks(`[[timeline:${ids.slice(0, 12).join(',')}]]`)[0].kind).toBe('timeline');
  });

  it('leaves tokens inside a code fence alone', () => {
    const t = `\`\`\`\n[[source:${A}]]\n\`\`\``;
    expect(splitBlocks(t)).toEqual([{ kind: 'text', text: t }]);
  });

  it('holds back an unfinished last line that starts with [[ while streaming', () => {
    expect(splitBlocks('Answer.\n[[sour', { streaming: true })).toEqual([{ kind: 'text', text: 'Answer.' }]);
    expect(splitBlocks(`Answer.\n[[source:${A}]]`, { streaming: true })).toEqual([{ kind: 'text', text: 'Answer.' }]);
    expect(splitBlocks(`Answer.\n[[source:${A}]]\n`, { streaming: true })).toEqual([
      { kind: 'text', text: 'Answer.' },
      { kind: 'source', factId: A },
    ]);
    expect(splitBlocks('Answer.\n[[sour')).toEqual([{ kind: 'text', text: 'Answer.\n[[sour' }]);
  });

  it('shows an unfinished last line that does not start with [[', () => {
    expect(splitBlocks('Answer [[sour', { streaming: true })).toEqual([{ kind: 'text', text: 'Answer [[sour' }]);
  });
});
