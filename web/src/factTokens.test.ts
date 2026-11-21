import { describe, expect, it } from 'vitest';
import { linkifyFactTokens, splitFactTokens } from './factTokens';

describe('splitFactTokens', () => {
  it('returns plain text unchanged', () => {
    expect(splitFactTokens('nothing here')).toEqual([{ kind: 'text', text: 'nothing here' }]);
  });

  it('turns f_ and u_ tokens into fact segments', () => {
    expect(splitFactTokens('See [f_65ed2f51cf] and [u_0123456789], done.')).toEqual([
      { kind: 'text', text: 'See ' },
      { kind: 'fact', factId: 'f_65ed2f51cf' },
      { kind: 'text', text: ' and ' },
      { kind: 'fact', factId: 'u_0123456789' },
      { kind: 'text', text: ', done.' },
    ]);
  });

  it('handles a token at the start and end, and adjacent tokens', () => {
    expect(splitFactTokens('[f_a1][f_b2]')).toEqual([
      { kind: 'fact', factId: 'f_a1' },
      { kind: 'fact', factId: 'f_b2' },
    ]);
  });

  it('leaves look-alikes alone', () => {
    const t = 'a [x_12] b [f_] c [f_12 d [link](f_12)';
    expect(splitFactTokens(t)).toEqual([{ kind: 'text', text: t }]);
  });

  it('does not treat markup as anything but text', () => {
    expect(splitFactTokens('<b>[f_a1]</b>')).toEqual([
      { kind: 'text', text: '<b>' },
      { kind: 'fact', factId: 'f_a1' },
      { kind: 'text', text: '</b>' },
    ]);
  });
});

describe('bare ids and linkifyFactTokens', () => {
  it('recognises bare ids but not short or embedded look-alikes', () => {
    expect(splitFactTokens('see f_892a19a7ce.')).toEqual([
      { kind: 'text', text: 'see ' },
      { kind: 'fact', factId: 'f_892a19a7ce' },
      { kind: 'text', text: '.' },
    ]);
    const t = 'f_12 and my_f_892a19a7ce and /f_892a19a7ce';
    expect(splitFactTokens(t)).toEqual([{ kind: 'text', text: t }]);
  });

  it('turns ids into fact links and groups adjacent ones', () => {
    expect(linkifyFactTokens('a f_892a19a7ce, [f_a0d7b72f9d] and f_cab5d82ad4 b')).toBe(
      'a [](fact:f_892a19a7ce,f_a0d7b72f9d,f_cab5d82ad4) b',
    );
  });

  it('drops parentheses that only wrap the ids', () => {
    expect(linkifyFactTokens('x (f_892a19a7ce, f_a0d7b72f9d).')).toBe('x [](fact:f_892a19a7ce,f_a0d7b72f9d).');
  });

  it('leaves code spans and fences alone', () => {
    const t = 'use `f_892a19a7ce` and\n```\nf_892a19a7ce\n```';
    expect(linkifyFactTokens(t)).toBe(t);
  });
});
