import { describe, expect, it } from 'vitest';
import { splitFactTokens } from './factTokens';

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
