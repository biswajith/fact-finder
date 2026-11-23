import { useCallback, useEffect, useRef, useState, type CSSProperties, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent } from 'react';
import { ChangesTab } from '../ChangesTab';
import { ChatLogTab } from '../ChatLogTab';
import { ChatPanel } from '../ChatPanel';
import { CompareTab } from '../CompareTab';
import { ConflictsTab } from '../ConflictsTab';
import { FactDetail } from '../FactDetail';
import { FactsTab } from '../FactsTab';
import { DocumentsPage } from '../bid/DocumentsPage';
import { ReportTab } from '../ReportTab';
import { OverviewTab } from '../OverviewTab';
import type { BidFlow } from '../../bidFlow';
import { CHAT_WIDTH_DEFAULT, CHAT_WIDTH_MAX, CHAT_WIDTH_MIN, clampChatWidth, readChatWidth, saveChatWidth } from '../../chatWidth';
import { useRun } from '../../store';
import { Sidebar } from './Sidebar';

const CHAT_KEY = 'rfp-facts-chat-open';
function readChatOpen(): boolean {
  try { return window.localStorage.getItem(CHAT_KEY) === '1'; } catch { return false; }
}

export function Workspace({ flow }: { flow: BidFlow }) {
  const { page, status, chatDraft, openFactId } = useRun();
  const [chatOpen, setChatOpenState] = useState(readChatOpen);
  const [menuOpen, setMenuOpen] = useState(false);
  // The chat drawer's width: dragged at its left edge (or arrow keys on the handle), kept for the next visit.
  const [chatWidth, setChatWidthState] = useState(() => clampChatWidth(readChatWidth(), window.innerWidth));
  const [resizing, setResizing] = useState(false);
  const setChatWidth = useCallback((w: number) => {
    const next = clampChatWidth(w, window.innerWidth);
    setChatWidthState(next);
    saveChatWidth(next);
  }, []);
  useEffect(() => {
    const on = () => setChatWidthState((w) => clampChatWidth(w, window.innerWidth));
    window.addEventListener('resize', on);
    return () => window.removeEventListener('resize', on);
  }, []);
  const onResizeDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    const panel = e.currentTarget.parentElement;
    if (!panel) return;
    const right = panel.getBoundingClientRect().right; // the fact panel may sit to the right of the chat
    setResizing(true);
    const move = (ev: PointerEvent) => setChatWidth(right - ev.clientX);
    const up = () => {
      setResizing(false);
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };
  const onResizeKey = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    const step = e.shiftKey ? 80 : 24;
    if (e.key === 'ArrowLeft') setChatWidth(chatWidth + step);
    else if (e.key === 'ArrowRight') setChatWidth(chatWidth - step);
    else if (e.key === 'Home') setChatWidth(CHAT_WIDTH_MAX);
    else if (e.key === 'End') setChatWidth(CHAT_WIDTH_MIN);
    else return;
    e.preventDefault();
  };
  const resizer = (
    <div
      className="chat-resizer"
      role="separator"
      aria-orientation="vertical"
      aria-label="Width of the assistant panel"
      aria-valuemin={CHAT_WIDTH_MIN}
      aria-valuemax={CHAT_WIDTH_MAX}
      aria-valuenow={chatWidth}
      tabIndex={0}
      title="Drag to resize. Double-click to reset."
      onPointerDown={onResizeDown}
      onKeyDown={onResizeKey}
      onDoubleClick={() => setChatWidth(CHAT_WIDTH_DEFAULT)}
    />
  );
  const setChatOpen = (v: boolean) => {
    setChatOpenState(v);
    try { window.localStorage.setItem(CHAT_KEY, v ? '1' : '0'); } catch { /* storage unavailable */ }
  };
  // "Ask in chat" opens the drawer.
  useEffect(() => {
    if (chatDraft) setChatOpen(true);
  }, [chatDraft]);
  // A new page starts at its top, not where the last page was scrolled to.
  const scroller = useRef<HTMLElement>(null);
  useEffect(() => {
    if (scroller.current) scroller.current.scrollTop = 0;
  }, [page]);
  // Escape closes the mobile menu.
  useEffect(() => {
    if (!menuOpen) return;
    const on = (e: KeyboardEvent) => { if (e.key === 'Escape') setMenuOpen(false); };
    window.addEventListener('keydown', on);
    return () => window.removeEventListener('keydown', on);
  }, [menuOpen]);

  return (
    <div className={`shell${chatOpen ? ' chat-open' : ''}${openFactId ? ' fact-open' : ''}${resizing ? ' chat-resizing' : ''}`} style={{ '--drawer-w': `${chatWidth}px` } as CSSProperties}>
      <Sidebar open={menuOpen} onNavigate={() => setMenuOpen(false)} flow={flow} />
      <div className={`scrim${menuOpen ? ' show' : ''}`} onClick={() => setMenuOpen(false)} aria-hidden />
      <div className="main-col">
        <div className="topbar">
          <button type="button" className="shell-btn menu-btn" aria-label="Menu" aria-expanded={menuOpen} aria-controls="app-sidebar" onClick={() => setMenuOpen((v) => !v)}>Menu</button>
          <span className="topbar-brand">RFP facts</span>
          <span className="spacer" />
          <button type="button" className="shell-btn" aria-expanded={chatOpen} aria-controls="app-chat" onClick={() => setChatOpen(!chatOpen)}>Assistant</button>
        </div>
        <main className="main-scroll" ref={scroller}>
          <div className="page">
            {page === 'overview' && <OverviewTab />}
            {page === 'facts' && <FactsTab />}
            {page === 'conflicts' && <ConflictsTab />}
            {page === 'changes' && <ChangesTab />}
            {page === 'report' && <ReportTab />}
            {page === 'compare' && <CompareTab />}
            {page === 'chatlog' && <ChatLogTab />}
            {page === 'documents' && <DocumentsPage flow={flow} status={status} />}
          </div>
        </main>
      </div>
      <ChatPanel open={chatOpen} onClose={() => setChatOpen(false)} resizer={resizer} />
      <FactDetail />
    </div>
  );
}
