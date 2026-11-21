import { describe, expect, it } from 'vitest';
import { SseParser } from './sse';
import { readEventStream } from './api';
import type { ChatEvent } from './types';

const ev = (o: object) => `data: ${JSON.stringify(o)}\n\n`;

describe('SseParser', () => {
  it('parses several events in one chunk', () => {
    const p = new SseParser();
    const out = p.push(ev({ type: 'text', delta: 'a' }) + ev({ type: 'changed', what: ['facts'] }));
    expect(out).toEqual([
      { type: 'text', delta: 'a' },
      { type: 'changed', what: ['facts'] },
    ]);
  });

  it('handles an event split across chunks, even mid-delimiter', () => {
    const p = new SseParser();
    const whole = ev({ type: 'text', delta: 'Hello world' });
    const out: ChatEvent[] = [];
    for (const piece of [whole.slice(0, 10), whole.slice(10, whole.length - 1), whole.slice(-1)]) {
      out.push(...p.push(piece));
    }
    expect(out).toEqual([{ type: 'text', delta: 'Hello world' }]);
  });

  it('handles CRLF, ignores comments, and skips bad JSON', () => {
    const p = new SseParser();
    const out = p.push(': ping\r\n\r\ndata: {oops\n\ndata: {"type":"done","message":{"id":"m_1"}}\r\n\r\n');
    expect(out).toHaveLength(1);
    expect(out[0].type).toBe('done');
  });

  it('flush returns a final unterminated event', () => {
    const p = new SseParser();
    expect(p.push('data: {"type":"text","delta":"x"}')).toEqual([]);
    expect(p.flush()).toEqual([{ type: 'text', delta: 'x' }]);
  });

  it('keeps multibyte text intact through readEventStream', async () => {
    const bytes = new TextEncoder().encode(ev({ type: 'text', delta: 'café €' }) + ev({ type: 'error', message: 'x' }));
    const stream = new ReadableStream<Uint8Array>({
      start(c) {
        for (let i = 0; i < bytes.length; i += 3) c.enqueue(bytes.slice(i, i + 3));
        c.close();
      },
    });
    const got: ChatEvent[] = [];
    await readEventStream(stream, (e) => got.push(e));
    expect(got).toEqual([
      { type: 'text', delta: 'café €' },
      { type: 'error', message: 'x' },
    ]);
  });
});
