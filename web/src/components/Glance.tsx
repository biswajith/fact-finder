import { useMemo, useState, type CSSProperties } from 'react';
import * as api from '../api';
import { useAsync } from '../hooks';
import { useRun } from '../store';
import type { BriefRow, OverviewEntry, ViewName } from '../types';
import { CATEGORY_NAMES } from '../types';
import { CATEGORY_COLORS } from './common';
import { ErrorBox, Loading, PageChip, ViewSwitch } from './common';

const SHOWN = 8; // lines a list shows before "Show all"

type OpenByText = (text: string) => (() => void) | null;

function Line({ text, page, open, sub, head, count }: {
  text: string; page: string; open: OpenByText; sub?: boolean; head?: boolean; count?: number;
}) {
  const go = open(text);
  return (
    <li className={sub ? 'sub' : head ? 'head' : undefined}>
      {go ? (
        <button type="button" className="linkbtn t wrap-text" aria-label={`Open fact: ${text}`} onClick={go}>{text}</button>
      ) : (
        <span className="t wrap-text">{text}{count ? ` (${count})` : ''}</span>
      )}
      <PageChip page={page} />
    </li>
  );
}

function Entries({ entries, open, limit = SHOWN }: { entries: OverviewEntry[]; open: OpenByText; limit?: number }) {
  if (entries.length === 0) return <div className="muted">None found in this view.</div>;
  const one = (e: OverviewEntry, i: number) =>
    e.children.length === 0 ? (
      <Line key={i} text={e.text} page={e.page} open={open} />
    ) : (
      <li key={i} style={{ display: 'block', padding: 0, border: 'none' }}>
        <ul className="olist">
          <Line text={e.text} page={e.page} open={() => null} head count={e.children.length} />
          {e.children.map((c, j) => <Line key={j} text={c.text} page={c.page} open={open} sub />)}
        </ul>
      </li>
    );
  return (
    <>
      <ul className="olist">{entries.slice(0, limit).map(one)}</ul>
      {entries.length > limit && (
        <details>
          <summary>Show all {entries.length}</summary>
          <ul className="olist">{entries.slice(limit).map((e, i) => one(e, i + limit))}</ul>
        </details>
      )}
    </>
  );
}

const total = (entries: OverviewEntry[]) => entries.reduce((n, e) => n + (e.children.length || 1), 0);

function Card({ title, code, count, note, children }: {
  title: string; code: string; count?: number; note?: string; children: React.ReactNode;
}) {
  return (
    <section className="ocard" style={{ '--c': CATEGORY_COLORS[code] ?? '#64748b' } as CSSProperties} aria-label={title}>
      <h3>{title}{count !== undefined && <span className="n">{count}</span>}</h3>
      {note && <div className="muted">{note}</div>}
      {children}
    </section>
  );
}

function Kv({ rows }: { rows: BriefRow[] }) {
  return (
    <div className="kv">
      {rows.map((r, i) => (
        <KvRow key={i} r={r} />
      ))}
    </div>
  );
}
function KvRow({ r }: { r: BriefRow }) {
  return (
    <>
      <div className="k">{r.row}</div>
      <div className="wrap-text">{r.text || <span className="none">Not stated in the RFP</span>}</div>
      <div><PageChip page={r.page} /></div>
    </>
  );
}

/** A summary card: its rows, and the facts behind them folded underneath. With no summary rows, the facts as lists. */
function SummaryCard({ title, code, rows, parts, note, open }: {
  title: string; code: string; rows: BriefRow[]; parts: { heading: string; entries: OverviewEntry[] }[]; note?: string; open: OpenByText;
}) {
  const n = parts.reduce((s, p) => s + total(p.entries), 0);
  const behind = parts.map((p, i) => p.entries.length > 0 || rows.length === 0 ? (
    <div key={i}>
      {p.heading && <h4>{p.heading} ({total(p.entries)})</h4>}
      <Entries entries={p.entries} open={open} limit={rows.length ? 10 ** 6 : SHOWN} />
    </div>
  ) : null);
  if (rows.length === 0) {
    return <Card title={title} code={code} count={n} note={note}>{behind}</Card>;
  }
  return (
    <Card title={title} code={code} note={note}>
      <Kv rows={rows} />
      {n > 0 && (
        <details>
          <summary>Show the {n} facts behind this</summary>
          {behind}
        </details>
      )}
    </Card>
  );
}

const COUNT_TILES: { key: 'needs_review' | 'conflicts' | 'risk' | 'mandatory' | 'unclear'; label: string; hint: string; tone?: string }[] = [
  { key: 'needs_review', label: 'Needs review', hint: 'facts the check could not confirm', tone: 'warn' },
  { key: 'conflicts', label: 'Conflicts', hint: 'facts the RFP contradicts itself on', tone: 'bad' },
  { key: 'risk', label: 'Risk flags', hint: 'facts flagged as a risk' },
  { key: 'mandatory', label: 'Mandatory', hint: 'must-do requirements' },
  { key: 'unclear', label: 'Unclear', hint: 'points to ask the buyer' },
];

export function Glance() {
  const { run, facts, liveFacts, openFact } = useRun();
  const [view, setView] = useState<ViewName>('All');
  // `facts.data` changes after every write, so a correction shows up here too.
  const ov = useAsync((signal) => api.getOverview(run, view, signal), [run, view, facts.data]);

  const byText = useMemo(() => {
    const m = new Map<string, string>();
    for (const f of liveFacts) if (!m.has(f.text)) m.set(f.text, f.fact_id);
    return m;
  }, [liveFacts]);
  const open: OpenByText = (text) => {
    const id = byText.get(text);
    return id ? () => openFact(id) : null;
  };

  if (ov.loading && !ov.data) return <Loading label="Loading the overview" />;
  if (ov.error && !ov.data) return <ErrorBox message={ov.error} onRetry={ov.reload} />;
  if (!ov.data) return null;
  const { overview: o, counts, has_post_award } = ov.data;
  const sm = o.summary;
  return (
    <section className="panel" aria-label="At a glance" aria-busy={ov.loading}>
      <div className="row">
        <h2 style={{ fontSize: 18, flex: 1, margin: 0 }}>At a glance</h2>
      </div>
      <ViewSwitch view={view} onChange={setView} hasPostAward={has_post_award} />
      {ov.error && <ErrorBox message={ov.error} onRetry={ov.reload} />}
      <div className="stats" role="list" aria-label="Counts">
        {COUNT_TILES.map((t) => (
          <div key={t.key} role="listitem" className={`stat ${counts[t.key] ? (t.tone ?? '') : ''}`}>
            <div className="l">{t.label}</div>
            <div className="v">{counts[t.key]}</div>
            <div className="h">{t.hint}</div>
          </div>
        ))}
      </div>
      {o.buyer.length > 0 ? (
        <Card title="Buyer information" code="B"><Kv rows={o.buyer} /></Card>
      ) : (
        <Card title={CATEGORY_NAMES.B} code="B" count={total(o.buyer_facts)} note="This run has no buyer brief; these are its buyer facts.">
          <Entries entries={o.buyer_facts} open={open} />
        </Card>
      )}
      <div className="glance-grid">
        <Card title="Calendar" code="D" count={o.calendar.dated.length + o.calendar.undated.length}>
          {o.calendar.dated.length > 0 ? (
            <div className="cal">
              {o.calendar.dated.map((d, i) => {
                const go = open(d.text);
                return (
                  <CalRow key={i} d={d} go={go} />
                );
              })}
            </div>
          ) : o.calendar.undated.length === 0 ? (
            <div className="muted">No dates found.</div>
          ) : null}
          {o.calendar.undated.length > 0 && (
            <>
              <h4>No fixed date ({o.calendar.undated.length})</h4>
              <Entries entries={o.calendar.undated.map((u) => ({ ...u, children: [] }))} open={open} />
            </>
          )}
        </Card>
        <SummaryCard title="Submission instructions" code="S" rows={sm.submission} parts={[{ heading: '', entries: o.submission }]} open={open} />
        <SummaryCard
          title="Go/no-go gates" code="G" rows={sm.gates} open={open}
          parts={[{ heading: 'To be allowed to bid', entries: o.gates }, { heading: 'What gets a proposal rejected', entries: o.disqualifiers }]}
        />
        <SummaryCard title="Scoring criteria" code="E" rows={sm.scoring} parts={[{ heading: '', entries: o.scoring }]} open={open} />
      </div>
      <SummaryCard
        title="Clarifications" code="Q" rows={sm.questions} open={open}
        note="Points to raise with the buyer before the question deadline."
        parts={[{ heading: 'The RFP contradicts itself', entries: o.contradictions }, { heading: 'Unclear, ask the buyer', entries: o.unclear }]}
      />
    </section>
  );
}

function CalRow({ d, go }: { d: { label: string; time: string; text: string; page: string }; go: (() => void) | null }) {
  return (
    <>
      <div className="d">{d.label}{d.time && <small>{d.time}</small>}</div>
      {go ? (
        <button type="button" className="linkbtn wrap-text" style={{ textAlign: 'left' }} aria-label={`Open fact: ${d.text}`} onClick={go}>{d.text}</button>
      ) : (
        <div className="wrap-text">{d.text}</div>
      )}
      <div><PageChip page={d.page} /></div>
    </>
  );
}
