import { describe, expect, it } from 'vitest';
import { argsText, cacheShare, groupTurns, turnTotals } from './chatLog';
import type { ChatLogEvent } from './types';

let seq = 0;
const ev = (turn_id: string, event: string, extra: Partial<ChatLogEvent> = {}): ChatLogEvent =>
  ({ at: '2026-11-21T10:00:00Z', session_id: 's_1', turn_id, seq: ++seq, event, ...extra }) as ChatLogEvent;

describe('groupTurns', () => {
  it('groups by turn and puts each tool run under the call that asked for it', () => {
    const turns = groupTurns([
      ev('t1', 'user_message', { text: 'hi' }),
      ev('t1', 'route', { mode: 'heavy' }),
      ev('t1', 'plan', { status: 'awaiting_approval' }),
      ev('t1', 'llm_call', { purpose: 'loop', input_tokens: 100, cached_tokens: 50 }),
      ev('t1', 'tool', { name: 'search' }),
      ev('t1', 'tool', { name: 'get_fact' }),
      ev('t1', 'llm_call', { purpose: 'loop', input_tokens: 200, cached_tokens: 150 }),
      ev('t1', 'plan', { status: 'approved' }),
      ev('t2', 'user_message', { text: 'yes' }),
      ev('t2', 'feedback', { verdict: 'approve' }),
      ev('t2', 'turn_end', { totals: { llm_calls: 0 } }),
    ]);
    expect(turns.map((t) => t.id)).toEqual(['t1', 't2']);
    const [one, two] = turns;
    expect(one.user).toBe('hi');
    expect(one.route?.mode).toBe('heavy');
    expect(one.calls.map((c) => c.tools.map((x) => x.name))).toEqual([['search', 'get_fact'], []]);
    expect(one.plan?.status).toBe('approved');
    expect(one.planUpdates).toBe(2);
    expect(turnTotals(one)).toMatchObject({ llm_calls: 2, tool_calls: 2, input_tokens: 300, cached_tokens: 200 });
    expect(two.feedback?.verdict).toBe('approve');
    expect(turnTotals(two)).toEqual({ llm_calls: 0 });
  });
  it('drops a tool event that comes before any call', () => {
    expect(groupTurns([ev('t1', 'tool', { name: 'search' })])[0].calls).toEqual([]);
  });
});

describe('formatting', () => {
  it('shows search queries first, then the other arguments', () => {
    expect(argsText({ queries: ['bids', 'bond'], category: 'R' })).toBe('“bids”, “bond” · category=R');
    expect(argsText({ query: 'deadline', limit: 5 })).toBe('“deadline” · limit=5');
    expect(argsText({ fact_id: 'f_1', done: [1, 2] })).toBe('fact_id=f_1 · done=[1,2]');
    expect(argsText(null)).toBe('');
  });
  it('gives the cached share of input', () => {
    expect(cacheShare(1000, 830)).toBe('83%');
    expect(cacheShare(0, 0)).toBe('–');
    expect(cacheShare(null, 5)).toBe('–');
  });
});
