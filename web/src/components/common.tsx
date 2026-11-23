import type { ReactNode } from 'react';
import { ActionGroup, Button, InlineAlert, Heading, Content, Item, ProgressCircle } from '@adobe/react-spectrum';
import { useRun } from '../store';
import type { Fact, ViewName } from '../types';

export function Loading({ label = 'Loading' }: { label?: string }) {
  return (
    <div className="centered">
      <ProgressCircle aria-label={label} isIndeterminate />
    </div>
  );
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <InlineAlert variant="negative">
      <Heading>Something went wrong</Heading>
      <Content>
        <div className="wrap-text">{message}</div>
        {onRetry && (
          <div style={{ marginTop: 8 }}>
            <Button variant="secondary" onPress={onRetry}>
              Try again
            </Button>
          </div>
        )}
      </Content>
    </InlineAlert>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="muted" style={{ padding: '24px 0', textAlign: 'center' }}>{children}</div>;
}

export function firstPage(f: Fact): string {
  const c = f.citations[0];
  return c ? c.page_label || String(c.page) : '';
}

/** A small link that opens a fact. Works for ids the facts list does not know too. */
export function FactLink({ id, label }: { id: string; label?: string }) {
  const { openFact, factById } = useRun();
  const f = factById.get(id);
  const text = label ?? (f ? `${f.category} p.${firstPage(f) || '?'}` : id);
  return (
    <button type="button" className="linkbtn" aria-label={`Open fact ${id}`} title={f ? f.text : id} onClick={() => openFact(id)}>
      {text}
    </button>
  );
}

export function formatTime(at: string | number | null | undefined): string {
  if (at === null || at === undefined || at === '') return '';
  const d = typeof at === 'number' ? new Date(at * 1000) : new Date(at);
  return Number.isNaN(d.getTime()) ? String(at) : d.toLocaleString();
}

/** Colour of a category on the cards and in the list. */
export const CATEGORY_COLORS: Record<string, string> = Object.fromEntries(
  ['B', 'C', 'G', 'X', 'D', 'S', 'E', 'R', 'Q'].map((c) => [c, `var(--cat-${c})`]),
);
export function PageChip({ page }: { page: string }) {
  return page ? <span className="pg">p. {page}</span> : null;
}

const VIEWS: ViewName[] = ['All', 'Bid', 'After award'];
export const VIEW_HELP =
  'Bid: what to know, decide and submit before the deadline, plus after-award obligations that carry a risk or an amount to price. ' +
  'After award: every obligation of the winning bidder.';

/** The All / Bid / After award switch, with the help text and the note for runs that mark nothing post-award. */
export function ViewSwitch({ view, onChange, hasPostAward }: { view: ViewName; onChange: (v: ViewName) => void; hasPostAward: boolean }) {
  return (
    <div className="view-switch" title={VIEW_HELP}>
      <ActionGroup
        aria-label="View"
        density="compact"
        selectionMode="single"
        disallowEmptySelection
        selectedKeys={[view]}
        onSelectionChange={(k) => onChange((([...k][0] as ViewName) ?? 'All'))}
      >
        {VIEWS.map((v) => <Item key={v}>{v}</Item>)}
      </ActionGroup>
      {!hasPostAward && view !== 'All' && (
        <span className="muted">This run marks nothing as post-award, so every view shows everything.</span>
      )}
    </div>
  );
}
