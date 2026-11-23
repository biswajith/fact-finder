import { describe, expect, it } from 'vitest';
import { CHAT_WIDTH_DEFAULT, CHAT_WIDTH_MAX, CHAT_WIDTH_MIN, clampChatWidth } from './chatWidth';

describe('clampChatWidth', () => {
  it('keeps a width inside the limits', () => {
    expect(clampChatWidth(600, 1600)).toBe(600);
    expect(clampChatWidth(100, 1600)).toBe(CHAT_WIDTH_MIN);
    expect(clampChatWidth(5000, 2400)).toBe(CHAT_WIDTH_MAX);
  });
  it('leaves room for the page in a narrow window', () => {
    expect(clampChatWidth(900, 1000)).toBe(680);
    expect(clampChatWidth(900, 500)).toBe(CHAT_WIDTH_MIN);
  });
  it('falls back to the default for a bad value', () => {
    expect(clampChatWidth(NaN, 1600)).toBe(CHAT_WIDTH_DEFAULT);
  });
});
