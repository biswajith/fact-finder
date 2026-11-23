import { useEffect, useRef, useState } from 'react';
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
    <div className={`shell${chatOpen ? ' chat-open' : ''}${openFactId ? ' fact-open' : ''}`}>
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
      <ChatPanel open={chatOpen} onClose={() => setChatOpen(false)} />
      <FactDetail />
    </div>
  );
}
