// The chat drawer's width: set by dragging its left edge, kept per browser.
export const CHAT_WIDTH_KEY = 'rfp-facts-chat-width';
export const CHAT_WIDTH_DEFAULT = 420;
export const CHAT_WIDTH_MIN = 340;
export const CHAT_WIDTH_MAX = 960;
/** Room always left for the page beside the chat. */
const PAGE_MIN = 320;

/** A width the drawer may have in a window `viewport` pixels wide. */
export function clampChatWidth(width: number, viewport: number): number {
  if (!Number.isFinite(width)) return CHAT_WIDTH_DEFAULT;
  const most = Math.max(CHAT_WIDTH_MIN, Math.min(CHAT_WIDTH_MAX, viewport - PAGE_MIN));
  return Math.round(Math.min(most, Math.max(CHAT_WIDTH_MIN, width)));
}

export function readChatWidth(): number {
  try {
    const v = Number(window.localStorage.getItem(CHAT_WIDTH_KEY));
    return v > 0 ? v : CHAT_WIDTH_DEFAULT;
  } catch {
    return CHAT_WIDTH_DEFAULT;
  }
}

export function saveChatWidth(width: number): void {
  try { window.localStorage.setItem(CHAT_WIDTH_KEY, String(width)); } catch { /* storage unavailable */ }
}
