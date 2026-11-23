import { useMemo, useState } from 'react';
import { Button } from '@adobe/react-spectrum';
import * as api from '../api';
import { useAsync } from '../hooks';
import { useRun } from '../store';
import type { CalendarDate, Fact, Overview, OverviewCounts, OverviewEntry, OverviewResponse, SummaryRow, SummarySection, ViewName } from '../types';
import { CATEGORY_COLORS, ErrorBox, Loading, PageChip, ViewSwitch, formatTime } from './common';
import { PageCites } from './CitationChip';
import { emptyFilters } from '../factsQuery';
import { openConflictCount, unverifiedNote } from '../overviewView';
import { AwardObligations } from './overview/AwardView';
import { CollapseProvider, ExpandCollapseAll, Section } from './overview/Collapsible';
import { PageHeader } from './shell/PageHeader';
import './overview.css';

type CardDef = { key: string; title: string; code: string };
/** Open until the reader folds them: what decides whether and how to bid. */
const OPEN_BY_DEFAULT = ['dates', 'submission', 'gates'];

/** The facts behind a card: its summary's whole-run count under All, the view's own count otherwise. */
function cardCount(view: ViewName, s: SummarySection | undefined, listCount: number, categoryCount: number | null): number {
  if (view === 'All') return s?.fact_count ?? listCount;
  return categoryCount ?? listCount;
}

/** Sections that need a summary run: stale, or with no rows yet. */
const needsSummary = (s: SummarySection) => s.stale || s.rows.length === 0;

const SHOWN = 6; // lines a list shows before "Show all"

type OpenByText = (text: string) => (() => void) | null;

/** The overview for a view, re-fetched after every fact write. */
function useOverview(view: ViewName) {
  const { run, facts } = useRun();
  return useAsync((signal) => api.getOverview(run, view, signal), [run, view, facts.data]);
}

/** The facts of a view (Bid, After award), from the same filter the Facts page uses; none loaded for All. */
function useViewFacts(view: ViewName) {
  const { run, facts } = useRun();
  return useAsync((signal) => api.getFactsList(run, { ...emptyFilters(), view }, signal), [run, view, facts.data], view !== 'All');
}

/** One line in a list. A fact opens when its text matches a live fact. */
function Line({ text, page, open, sub, head, count }: {
  text: string; page: string; open: OpenByText; sub?: boolean; head?: boolean; count?: number;
}) {
  const go = open(text);
  return (
    <li className={`ov-line${sub ? ' sub' : ''}${head ? ' head' : ''}`}>
      {go ? (
        <button type="button" className="ov-open wrap-text" aria-label={`Open fact: ${text}`} onClick={go}>{text}</button>
      ) : (
        <span className="ov-t wrap-text">{text}{count ? ` (${count})` : ''}</span>
      )}
      <PageChip page={page} />
    </li>
  );
}

function Entries({ entries, open, limit = SHOWN }: { entries: OverviewEntry[]; open: OpenByText; limit?: number }) {
  const [all, setAll] = useState(false);
  if (entries.length === 0) return <div className="ov-none">None found in this view.</div>;
  const one = (e: OverviewEntry, i: number) =>
    e.children.length === 0 ? (
      <Line key={i} text={e.text} page={e.page} open={open} />
    ) : (
      <li key={i} className="ov-group">
        <ul className="ov-list">
          <Line text={e.text} page={e.page} open={() => null} head count={e.children.length} />
          {e.children.map((c, j) => <Line key={j} text={c.text} page={c.page} open={open} sub />)}
        </ul>
      </li>
    );
  const shown = all ? entries : entries.slice(0, limit);
  return (
    <>
      <ul className="ov-list">{shown.map(one)}</ul>
      {entries.length > limit && (
        <button type="button" className="ov-more" aria-expanded={all} onClick={() => setAll(!all)}>
          {all ? 'Show fewer' : `Show all ${entries.length}`}
        </button>
      )}
    </>
  );
}

const total = (entries: OverviewEntry[]) => entries.reduce((n, e) => n + (e.children.length || 1), 0);

const BEHIND: Record<string, (o: Overview) => { heading: string; entries: OverviewEntry[] }[]> = {
  buyer: (o) => [{ heading: '', entries: o.buyer_facts }],
  submission: (o) => [{ heading: '', entries: o.submission }],
  gates: (o) => [{ heading: 'To be allowed to bid', entries: o.gates }, { heading: 'What gets a proposal rejected', entries: o.disqualifiers }],
  scoring: (o) => [{ heading: '', entries: o.scoring }],
  questions: (o) => [{ heading: 'The RFP contradicts itself', entries: o.contradictions }, { heading: 'Unclear, ask the buyer', entries: o.unclear }],
};

/** A row's text; a run of items joined by semicolons shows one item per line (display only). */
function RowText({ text, empty }: { text: string; empty: string }) {
  if (!text) return <span className="wrap-text"><span className="ov-none">{empty}</span></span>;
  const items = text.split(/;\s+/).filter(Boolean);
  if (items.length < 2) return <span className="wrap-text">{text}</span>;
  return <ul className="ov-kv-items">{items.map((t, i) => <li key={i} className="wrap-text">{t}</li>)}</ul>;
}

function Rows({ rows }: { rows: SummaryRow[] }) {
  return (
    <dl className="ov-kv">
      {rows.map((r, i) => (
        <div key={i} className={`ov-kv-row${r.unverified ? ' unverified' : ''}`}>
          <dt>{r.row}</dt>
          <dd>
            {r.unverified && (
              <span className="ov-unverified" role="note">
                <span className="pill warn">Not verified</span>
                <span>{unverifiedNote(r)}</span>
              </span>
            )}
            <RowText text={r.text} empty={r.unverified ? 'Nothing to show' : 'Not stated in the RFP'} />
            {r.fact_ids.length > 0 ? <PageCites ids={r.fact_ids} /> : <PageChip page={r.page} />}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function Parts({ parts, open }: { parts: { heading: string; entries: OverviewEntry[] }[]; open: OpenByText }) {
  return (
    <>
      {parts.map((p, i) => (
        <div key={i} className="ov-part">
          {p.heading && <h4>{p.heading} <span>{total(p.entries)}</span></h4>}
          <Entries entries={p.entries} open={open} />
        </div>
      ))}
    </>
  );
}

function StatusBadge({ s, busy, noKey, onUpdate }: { s: SummarySection; busy: boolean; noKey: boolean; onUpdate: () => void }) {
  if (s.updating) return <span className="pill info" role="status">Updating…</span>;
  if (s.stale) {
    return (
      <>
        <span className="pill warn">Out of date</span>
        <button type="button" className="ov-upd" disabled={busy || noKey} title={noKey ? 'No API key: summaries are off' : `Update the ${s.title} summary`} onClick={onUpdate}>Update</button>
      </>
    );
  }
  if (s.rows.length === 0) return null;
  const tip = s.source === 'extraction' ? 'From the extraction' : s.generated_at ? `Updated ${formatTime(s.generated_at)}` : undefined;
  if (!tip) return null;
  return (
    <span className="ov-src" title={tip} aria-label={tip} role="img">
      <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
        <circle cx="8" cy="8" r="6.5" fill="none" stroke="currentColor" strokeWidth="1.3" />
        <path d="M8 7.2v4M8 4.6v.1" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      </svg>
    </span>
  );
}

/** One summary card: its rows with citations, and the facts behind them folded underneath. */
function SummaryCard({ def, s, o, open, view, byCategory }: {
  def: CardDef; s?: SummarySection; o: Overview; open: OpenByText;
  view: ViewName; byCategory: Record<string, number>;
}) {
  const { run, act, setSummaries, status, showFacts, factById, openFact } = useRun();
  const [behindOpen, setBehindOpen] = useState(false);
  const [unusedOpen, setUnusedOpen] = useState(false);
  const noKey = status?.has_key === false;
  const parts = BEHIND[def.key]?.(o) ?? [];
  const listCount = parts.reduce((n, p) => n + total(p.entries), 0);
  // A section with no fact list in /api/overview (contract, requirements): the Facts page is the way in.
  const factsCat = BEHIND[def.key] ? undefined : def.code;
  const count = cardCount(view, s, listCount, factsCat ? byCategory[factsCat] ?? 0 : null);
  const rows = s?.rows ?? [];
  const summarised = rows.length > 0;
  const busy = !!s?.updating;
  const generate = async () => {
    const r = await act(() => api.generateSummaries(run, [def.key]));
    if (r) setSummaries(r);
  };
  const uncovered = (s?.uncovered ?? []).map((id) => factById.get(id)).filter((f): f is Fact => !!f);
  const seeAll = factsCat ? (
    <button type="button" className="linkbtn" onClick={() => showFacts({ categories: [factsCat], view })}>Show the {count} facts in Facts</button>
  ) : null;
  return (
    <Section
      id={def.key} className="ov-card" title={def.title} color={CATEGORY_COLORS[def.code] ?? 'var(--cat-B)'} count={count}
      status={s ? <StatusBadge s={s} busy={busy} noKey={noKey} onUpdate={() => void generate()} /> : undefined}
      hint={s?.stale ? 'Out of date' : undefined}
    >
      {s?.error && <div className="ov-error" role="alert">{s.error}</div>}
      {summarised ? (
        <>
          <Rows rows={rows} />
          <div className="ov-foot">
            {parts.length > 0 && (
              <button type="button" aria-expanded={behindOpen} onClick={() => setBehindOpen(!behindOpen)}>
                {behindOpen ? 'Hide' : 'Show'} the {count} facts
              </button>
            )}
            {seeAll && <span>{seeAll}</span>}
            {(s?.uncovered.length ?? 0) > 0 && (
              <button type="button" aria-expanded={unusedOpen} onClick={() => setUnusedOpen(!unusedOpen)}>
                {s!.uncovered.length} facts not used in this summary
              </button>
            )}
          </div>
          {unusedOpen && (
            <div>
              {uncovered.map((f) => (
                <div key={f.fact_id} className="ov-unused">
                  <span className="wrap-text">{f.text}</span>
                  <button type="button" className="linkbtn" aria-label={`Open fact: ${f.text}`} onClick={() => openFact(f.fact_id)}>Open</button>
                </div>
              ))}
            </div>
          )}
          {behindOpen && <Parts parts={parts} open={open} />}
        </>
      ) : (
        <>
          {s && (
            <div className="ov-empty">
              <span>{s.updating ? 'Summarising…' : 'Not summarised yet'}</span>
              <button type="button" className="ov-upd" disabled={busy || noKey}
                title={noKey ? 'No API key: summaries are off' : undefined} onClick={() => void generate()}>Summarise</button>
            </div>
          )}
          {seeAll}
          <Parts parts={parts} open={open} />
        </>
      )}
    </Section>
  );
}
// ---- Counts as buttons ----
type CountKey = keyof OverviewCounts;
const COUNT_TILES: { key: CountKey; label: string; hint: string; tone?: 'warn' | 'bad' }[] = [
  { key: 'needs_review', label: 'Needs review', hint: 'could not be confirmed', tone: 'warn' },
  { key: 'conflicts', label: 'Conflicts', hint: 'need your choice', tone: 'bad' },
  { key: 'risk', label: 'Risk flags', hint: 'flagged as a risk' },
  { key: 'mandatory', label: 'Mandatory', hint: 'must-do requirements' },
  { key: 'unclear', label: 'Unclear', hint: 'to ask the buyer' },
];

function StatTiles({ counts, view, viewFactIds }: { counts: OverviewCounts; view: ViewName; viewFactIds: ReadonlySet<string> | null }) {
  const { goTo, showFacts, conflicts } = useRun();
  const openConflicts = openConflictCount(conflicts.data ?? [], view, viewFactIds);
  const go = (k: CountKey) => {
    if (k === 'conflicts') return goTo('conflicts');
    if (k === 'needs_review') showFacts({ statuses: ['needs_review'], view });
    else showFacts({ flags: [k], view });
  };
  return (
    <div className="ov-stats" role="group" aria-label="Counts">
      {COUNT_TILES.map((t) => {
        const n = t.key === 'conflicts' ? openConflicts : counts[t.key];
        if (!n) return null;
        const hint = t.key === 'conflicts' && view !== 'All' ? 'in this view, need your choice' : t.hint;
        return (
          <button key={t.key} type="button" className={`ov-stat${t.tone ? ` ${t.tone}` : ''}`} title={`${n} ${hint}`}
            aria-label={`${t.label}: ${n}, ${hint}. ${t.key === 'conflicts' ? 'Open conflicts' : 'Show these facts'}`} onClick={() => go(t.key)}>
            <span className="l">{t.label}</span>
            <span className="v">{n}</span>
          </button>
        );
      })}
    </div>
  );
}

// ---- Key dates ----
const parseDate = (s: string): number | null => {
  if (!/^\d{4}-\d{2}-\d{2}/.test(s.trim())) return null;
  const m = s.trim().match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!m) return null;
  const t = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])).getTime();
  return Number.isNaN(t) ? null : t;
};

function KeyDates({ dated, undated, open }: {
  dated: CalendarDate[]; undated: { text: string; page: string }[]; open: OpenByText;
}) {
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const times = dated.map((d) => parseDate(d.date));
  const nextIdx = times.findIndex((t) => t !== null && t >= today.getTime());
  const n = dated.length + undated.length;
  return (
    <Section id="dates" className="ov-dates" title="Key dates" color="var(--cat-D)" count={n}>
      {n === 0 && <div className="ov-none">No dates found.</div>}
      {dated.length > 0 && (
        <ol className="ov-timeline">
          {dated.map((d, i) => {
            const t = times[i];
            const past = t !== null && t < today.getTime();
            const next = i === nextIdx;
            const go = open(d.text);
            return (
              <li key={i} className={`ov-ev${past ? ' past' : ''}${next ? ' next' : ''}`} aria-current={next ? 'date' : undefined}>
                <div className="ov-when">
                  <span className="ov-date">{d.label}</span>
                  {d.time && <span className="ov-time">{d.time}</span>}
                </div>
                <div className="ov-what">
                  {next && <span className="pill info ov-nextpill">Next</span>}
                  {go ? (
                    <button type="button" className="ov-open wrap-text" aria-label={`Open fact: ${d.text}`} onClick={go}>{d.text}</button>
                  ) : (
                    <span className="wrap-text">{d.text}</span>
                  )}
                  <PageChip page={d.page} />
                </div>
              </li>
            );
          })}
        </ol>
      )}
      {undated.length > 0 && (
        <details className="ov-details">
          <summary>No fixed date ({undated.length})</summary>
          <Entries entries={undated.map((u) => ({ ...u, children: [] }))} open={open} />
        </details>
      )}
    </Section>
  );
}

/** Subtitle for the page header: the buyer rows when present. */
function buyerLine(rows: SummaryRow[]): string {
  const pick = (re: RegExp) => rows.find((r) => re.test(r.row) && r.text)?.text;
  const name = pick(/buyer|issuer|agency|organi[sz]ation|client|customer|entity/i) ?? rows.find((r) => r.text)?.text;
  const id = pick(/rfp|solicitation|reference|number|tender|ref/i);
  const parts = [name, id && id !== name ? id : undefined].filter(Boolean) as string[];
  return parts.join(' · ');
}

function OverviewBody({ ov, view }: {
  ov: ReturnType<typeof useOverview>; view: ViewName;
}) {
  const { liveFacts, factById, openFact, summaries } = useRun();
  const viewFacts = useViewFacts(view);
  const secs = summaries.data?.sections ?? [];
  const byText = useMemo(() => {
    const m = new Map<string, string>();
    for (const f of liveFacts) if (!m.has(f.text)) m.set(f.text, f.fact_id);
    return m;
  }, [liveFacts]);
  const viewIds = useMemo(() => (viewFacts.data ? viewFacts.data.items.flatMap((it) => it.fact_ids) : null), [viewFacts.data]);
  const viewFactIds = useMemo(() => (viewIds ? new Set(viewIds) : null), [viewIds]);
  const awardFacts = useMemo(() => (viewIds ?? []).map((id) => factById.get(id)).filter((f): f is Fact => !!f), [viewIds, factById]);
  const open: OpenByText = (text) => {
    const id = byText.get(text);
    return id ? () => openFact(id) : null;
  };
  const data: OverviewResponse | null = ov.data;
  if (!data) return null;
  const { overview: o, counts } = data;
  const cards: CardDef[] = secs.map((s) => ({ key: s.key, title: s.title, code: s.codes[0] ?? 'B' }));
  const ids = ['dates', ...cards.map((d) => d.key)];
  const tiles = <StatTiles counts={counts} view={view} viewFactIds={viewFactIds} />;
  if (view === 'After award') {
    return (
      <div className="ov-glance" aria-busy={ov.loading || viewFacts.loading}>
        <p className="ov-note ov-viewnote">
          This lists what the winning bidder must do after award. The section summaries describe the whole RFP and are shown under All and Bid.
        </p>
        {tiles}
        {viewFacts.error && !viewFacts.data ? (
          <ErrorBox message={viewFacts.error} onRetry={viewFacts.reload} />
        ) : !viewFacts.data ? (
          <Loading label="Loading after-award facts" />
        ) : (
          <AwardObligations facts={awardFacts} hasPostAward={data.has_post_award} />
        )}
      </div>
    );
  }
  const differs = view === 'Bid' && secs.some((s) => {
    const listCount = (BEHIND[s.key]?.(o) ?? []).reduce((n, p) => n + total(p.entries), 0);
    const cat = BEHIND[s.key] ? null : data.by_category[s.codes[0]] ?? 0;
    return cardCount(view, s, listCount, cat) !== s.fact_count;
  });
  return (
    <div className="ov-glance" aria-busy={ov.loading}>
      {differs && (
        <p className="ov-note ov-viewnote">
          The summary rows describe the whole RFP. The fact counts and lists below show only what is in the Bid view.
        </p>
      )}
      {tiles}
      <CollapseProvider defaultOpen={OPEN_BY_DEFAULT}>
        <ExpandCollapseAll ids={ids} />
        <div className="ov-stack">
          <KeyDates dated={o.calendar.dated} undated={o.calendar.undated} open={open} />
          {cards.map((d) => (
            <SummaryCard key={d.key} def={d} s={secs.find((x) => x.key === d.key)} o={o} open={open} view={view} byCategory={data.by_category} />
          ))}
        </div>
      </CollapseProvider>
    </div>
  );
}

/** The Overview page: header, view switch and the cards. */
export function OverviewTab() {
  const { summaries, run, act, setSummaries, reloadAll, runInfo, status } = useRun();
  const [view, setView] = useState<ViewName>('All');
  const ov = useOverview(view);
  const sections = summaries.data?.sections ?? [];
  const anyBusy = summaries.data?.updating ?? false;
  const noKey = status?.has_key === false;
  const todo = sections.filter(needsSummary).map((s) => s.key);
  const subtitle = buyerLine(sections.find((s) => s.key === 'buyer')?.rows ?? []) || runInfo?.doc_id || undefined;
  return (
    <div className="ov-page">
      <PageHeader
        title="Overview"
        subtitle={subtitle}
        actions={
          <>
            {todo.length > 0 && view !== 'After award' && (
              <Button
                variant="secondary"
                isQuiet
                isDisabled={anyBusy || noKey}
                onPress={async () => {
                  const r = await act(() => api.generateSummaries(run, todo));
                  if (r) setSummaries(r);
                }}
              >
                <span title={noKey ? 'No API key: summaries are off' : anyBusy ? 'Summaries are updating' : undefined}>Update summaries</span>
              </Button>
            )}
            <ViewSwitch view={view} onChange={setView} hasPostAward={ov.data?.has_post_award ?? true} />
          </>
        }
      />
      {summaries.error && !summaries.data && <ErrorBox message={summaries.error} onRetry={() => void reloadAll()} />}
      {ov.loading && !ov.data ? (
        <Loading label="Loading the overview" />
      ) : ov.error && !ov.data ? (
        <ErrorBox message={ov.error} onRetry={ov.reload} />
      ) : (
        <>
          {ov.error && <ErrorBox message={ov.error} onRetry={ov.reload} />}
          <OverviewBody ov={ov} view={view} />
        </>
      )}
    </div>
  );
}
