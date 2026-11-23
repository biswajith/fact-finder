import { createContext, useCallback, useContext, useId, useMemo, useState, type CSSProperties, type ReactNode } from 'react';

const KEY = (id: string) => `ov-open:${id}`;

function readStored(id: string): boolean | undefined {
  try {
    const v = window.localStorage.getItem(KEY(id));
    return v === '0' ? false : v === '1' ? true : undefined;
  } catch {
    return undefined;
  }
}
function writeStored(id: string, open: boolean) {
  try {
    window.localStorage.setItem(KEY(id), open ? '1' : '0');
  } catch {
    /* storage unavailable: state lives in memory only */
  }
}

type Ctx = { isOpen: (id: string) => boolean; setOpen: (id: string, open: boolean) => void; setAll: (ids: string[], open: boolean) => void };
const Fallback: Ctx = { isOpen: () => true, setOpen: () => undefined, setAll: () => undefined };
const CollapseCtx = createContext<Ctx>(Fallback);

/** Holds each overview section's open/closed state, remembered in localStorage; until the reader
 * picks, a section is open when it is in `defaultOpen` (all open when that is not given). */
export function CollapseProvider({ defaultOpen, children }: { defaultOpen?: string[]; children: ReactNode }) {
  const [state, setState] = useState<Record<string, boolean>>({});
  const isOpen = useCallback((id: string) => state[id] ?? readStored(id) ?? (defaultOpen ? defaultOpen.includes(id) : true), [state, defaultOpen]);
  const setOpen = useCallback((id: string, open: boolean) => {
    writeStored(id, open);
    setState((s) => ({ ...s, [id]: open }));
  }, []);
  const setAll = useCallback((ids: string[], open: boolean) => {
    ids.forEach((id) => writeStored(id, open));
    setState((s) => ({ ...s, ...Object.fromEntries(ids.map((id) => [id, open])) }));
  }, []);
  const value = useMemo(() => ({ isOpen, setOpen, setAll }), [isOpen, setOpen, setAll]);
  return <CollapseCtx.Provider value={value}>{children}</CollapseCtx.Provider>;
}

export function ExpandCollapseAll({ ids }: { ids: string[] }) {
  const { setAll } = useContext(CollapseCtx);
  return (
    <div className="ov-bulk" role="group" aria-label="Sections">
      <button type="button" className="ov-bulk-btn" onClick={() => setAll(ids, true)}>Expand all</button>
      <button type="button" className="ov-bulk-btn" onClick={() => setAll(ids, false)}>Collapse all</button>
    </div>
  );
}

/** A collapsible overview card: the whole header is the toggle; the body is not rendered while collapsed. */
export function Section({ id, title, color, count, hint, status, className, children }: {
  id: string; title: string; color: string; count?: number; hint?: string; status?: ReactNode; className: string; children: ReactNode;
}) {
  const { isOpen, setOpen } = useContext(CollapseCtx);
  const open = isOpen(id);
  const bodyId = useId();
  return (
    <section className={`${className}${open ? '' : ' collapsed'}`} style={{ '--c': color } as CSSProperties} aria-label={title}>
      <h3 className="ov-card-h">
        <div className="ov-head">
        <button type="button" className="ov-toggle" aria-expanded={open} aria-controls={bodyId} onClick={() => setOpen(id, !open)}>
          <svg className="ov-chev" width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
            <path d="M5 3l5 5-5 5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <span className="ov-dot" aria-hidden="true" />
          <span className="ov-title">{title}</span>
          {!open && hint && <span className="ov-hint">{hint}</span>}
        </button>
        {status && <span className="ov-status">{status}</span>}
        {count !== undefined && <span className="ov-count">{count}</span>}
        </div>
      </h3>
      {open && <div id={bodyId} className="ov-body">{children}</div>}
    </section>
  );
}
