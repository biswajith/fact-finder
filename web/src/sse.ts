import type { ChatEvent } from './types';

/**
 * Incremental parser for a text/event-stream body. Feed it chunks as they arrive
 * (events may be split across chunks); it returns the complete events found so far.
 * Only `data:` lines are used; each event's data lines are joined and parsed as JSON.
 * Events that are not valid JSON are skipped.
 */
export class SseParser {
  private buffer = '';

  push(chunk: string): ChatEvent[] {
    this.buffer += chunk;
    // Normalise line endings, then split on blank lines.
    this.buffer = this.buffer.replace(/\r\n?/g, '\n');
    const out: ChatEvent[] = [];
    let idx: number;
    while ((idx = this.buffer.indexOf('\n\n')) !== -1) {
      const raw = this.buffer.slice(0, idx);
      this.buffer = this.buffer.slice(idx + 2);
      const ev = parseEvent(raw);
      if (ev) out.push(ev);
    }
    return out;
  }

  /** Call at end of stream: a final event with no trailing blank line is still parsed. */
  flush(): ChatEvent[] {
    const raw = this.buffer;
    this.buffer = '';
    const ev = raw.trim() ? parseEvent(raw) : null;
    return ev ? [ev] : [];
  }
}

function parseEvent(raw: string): ChatEvent | null {
  const data: string[] = [];
  for (const line of raw.split('\n')) {
    if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''));
  }
  if (!data.length) return null;
  try {
    const value = JSON.parse(data.join('\n'));
    return value && typeof value.type === 'string' ? (value as ChatEvent) : null;
  } catch {
    return null;
  }
}
