import { describe, expect, it } from 'vitest';
import { planLines, planMessage, splitBlocks } from './chatBlocks';

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


describe('planLines', () => {
  it('puts each step of a one-line plan on its own line', () => {
    expect(planLines({ plan_text: 'Plan: 1. Look up the dates; 2. report them with sources.' })).toBe('1. Look up the dates\n2. report them with sources.');
    expect(planLines({ plan_text: 'Plan: 1) find it 2) fix it' })).toBe('1) find it\n2) fix it');
  });
  it('numbers the steps of a heavy plan and copes with nothing', () => {
    expect(planLines({ steps: [{ step: 'Find all dates' }, { step: 'Check each' }] })).toBe('1. Find all dates\n2. Check each');
    expect(planLines(null)).toBe('');
  });
});

describe('planMessage', () => {
  it('splits a one-line plan into steps and pulls a long topic list out as items', () => {
    const p = planMessage('Plan: 1. Look up the pricing drivers across the bid documents, including scope, volumes, contract and payment terms, evaluation, and budget signals; 2. summarize each factor and note what the documents do not address.\n\nShall I go ahead? You can also tell me what to change.');
    expect(p).toEqual({
      steps: [
        { text: 'Look up the pricing drivers across the bid documents', items: ['scope', 'volumes', 'contract and payment terms', 'evaluation', 'budget signals'], done: false },
        { text: 'Summarize each factor and note what the documents do not address.', items: [], done: false },
      ],
      rest: 'Shall I go ahead? You can also tell me what to change.',
    });
  });

  it('reads a numbered plan with done steps', () => {
    const p = planMessage('Plan:\n1. [done] find the dates\n2. report them\n\nShall I go ahead?');
    expect(p?.steps.map((s) => [s.text, s.done])).toEqual([['Find the dates', true], ['Report them', false]]);
  });

  it('leaves short lists in the sentence and ignores other messages', () => {
    expect(planMessage('Plan: 1. check dates, including May and June; 2. report')?.steps[0].items).toEqual([]);
    expect(planMessage('The plan is fine.')).toBeNull();
  });
});
