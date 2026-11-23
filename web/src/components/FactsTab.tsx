import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import { Button, Checkbox, CheckboxGroup, Dialog, DialogContainer, DialogTrigger, RangeSlider, SearchField, Switch } from '@adobe/react-spectrum';
import * as api from '../api';
import { useBidDocs, levelChip } from '../bidDocs';
import { emptyFilters, ALL_STATUSES, listEntries, paginate, PAGE_SIZES, withoutReplaced, type ListEntry } from '../factsQuery';
import { useAsync, useDebounced } from '../hooks';
import { useRun } from '../store';
import type { Fact, FactsListFilters, FactStatus, Flag, ViewName } from '../types';
import { BID_FLAGS, CATEGORY_CODES, FLAGS } from '../types';
import { DocCite } from './CitationChip';
import { ErrorBox, Loading, ViewSwitch, firstPage } from './common';
import { AddFactDialog } from './FactDetail';
import { PageHeader } from './shell/PageHeader';
import { CatPill, FactTags, STATUS_LABEL, categoryName, flagName } from './facts/parts';
import './facts.css';

function FactRow({ f, stated = 1, pages, noCites }: { f: Fact; stated?: number; pages?: string; noCites?: boolean }) {
  const { openFact, openFactId } = useRun();
  const { inBid } = useBidDocs();
  const label = pages ?? firstPage(f);
  const replaced = inBid && f.flags.includes('replaced');
  return (
    <button
      type="button"
      className={`fx-row${f.deleted ? ' deleted' : ''}${replaced ? ' replaced' : ''}`}
      aria-current={openFactId === f.fact_id ? 'true' : undefined}
      aria-label={`Open fact ${f.fact_id}: ${f.text}`}
      onClick={() => openFact(f.fact_id)}
    >
      <CatPill code={f.category} />
      <span className="fx-text">
        <span className="fx-t">{f.text}</span><span className="fx-meta"><FactTags f={f} stated={stated} /></span>
        {inBid && f.stale && <span className="fx-stale">Check: {f.stale}</span>}
      </span>
      {inBid ? (
        <span className="fx-pg fx-cites">{!noCites && f.citations.map((c) => <DocCite key={`${c.doc_id}|${c.id}`} c={c} />)}</span>
      ) : (
        <span className="fx-pg">{label ? `p. ${label}` : ''}</span>
      )}
    </button>
  );
}

/** A point stated in several documents: the governing fact once, every member's citations, and Ungroup. */
function SameRow({ e }: { e: ListEntry }) {
  const { run, act, openFact } = useRun();
  const { inBid } = useBidDocs();
  const [busy, setBusy] = useState(false);
  const gid = e.first.group_id;
  if (!inBid || !gid) return <FactRow f={e.first} stated={e.stated} pages={e.pages} />;
  const ungroup = async () => {
    setBusy(true);
    await act(() => api.ungroup(run, gid), 'Ungrouped. Undo it on the Changes page.');
    setBusy(false);
  };
  return (
    <div className="fx-same">
      <FactRow f={e.first} stated={e.stated} pages={e.pages} noCites />
      <div className="fx-same-foot">
        <span className="fx-cites">
          {e.facts.flatMap((m) => m.citations.map((c) => <DocCite key={`${m.fact_id}|${c.doc_id}|${c.id}`} c={c} onPress={() => openFact(m.fact_id)} />))}
        </span>
        <Button variant="secondary" isDisabled={busy} onPress={ungroup} aria-label={`Ungroup: ${e.first.text}`}>Ungroup</Button>
      </div>
    </div>
  );
}

function GroupCard({ e }: { e: ListEntry }) {
  const { openFactId } = useRun();
  const inside = openFactId !== null && e.facts.some((f) => f.fact_id === openFactId);
  return (
    <details className="fx-group" style={{ '--c': `var(--cat-${e.first.category}, var(--cat-B))` } as CSSProperties} open={inside || undefined}>
      <summary aria-label={`${e.title}, ${e.facts.length} related statements. Show or hide them`}>
        <CatPill code={e.first.category} />
        <span className="gt">{e.title}<small>{e.facts.length} related statements</small></span>
        <span className="fx-pg">{e.pages ? `p. ${e.pages}` : ''}</span>
      </summary>
      {e.facts.map((f) => <FactRow key={f.fact_id} f={f} />)}
    </details>
  );
}

function CategoryMenu({ f, set, byCat, codes }: {
  f: FactsListFilters; set: (p: Partial<FactsListFilters>) => void; byCat: Record<string, number>; codes: string[];
}) {
  const n = f.categories.length;
  return (
    <DialogTrigger type="popover">
      <Button variant="secondary" aria-label="Category filter">{n === 0 ? 'All categories' : `${n} ${n === 1 ? 'category' : 'categories'}`}</Button>
      <Dialog aria-label="Categories">
        <div className="fx-pop">
          <CheckboxGroup aria-label="Categories" value={f.categories} onChange={(v) => set({ categories: v })}>
            {codes.map((c) => <Checkbox key={c} value={c}>{`${categoryName(c)} (${byCat[c] ?? 0})`}</Checkbox>)}
          </CheckboxGroup>
          {n > 0 && <button type="button" className="fx-clear" style={{ alignSelf: 'flex-start' }} onClick={() => set({ categories: [] })}>Show all categories</button>}
        </div>
      </Dialog>
    </DialogTrigger>
  );
}

function FiltersMenu({ f, set, pages, count }: { f: FactsListFilters; set: (p: Partial<FactsListFilters>) => void; pages: number; count: number }) {
  const { inBid, docs } = useBidDocs();
  const [range, setRange] = useState({ start: f.pageFrom ?? 1, end: f.pageTo ?? Math.max(1, pages) });
  useEffect(() => setRange({ start: f.pageFrom ?? 1, end: f.pageTo ?? Math.max(1, pages) }), [f.pageFrom, f.pageTo, pages]);
  return (
    <DialogTrigger type="popover">
      <Button variant="secondary" aria-label={count ? `Filters, ${count} active` : 'Filters'}>
        Filters{count > 0 && <span className="fx-trigger-badge" aria-hidden>{count}</span>}
      </Button>
      <Dialog aria-label="Filters">
        <div className="fx-pop">
          <div className="fx-pop-group">
            <h4>Status</h4>
            <CheckboxGroup aria-label="Status" value={f.statuses} onChange={(v) => set({ statuses: v as FactStatus[] })}>
              {ALL_STATUSES.map((s) => <Checkbox key={s} value={s}>{STATUS_LABEL[s]}</Checkbox>)}
            </CheckboxGroup>
          </div>
          <div className="fx-pop-group">
            <h4>Flags (any of)</h4>
            <CheckboxGroup aria-label="Flags" value={f.flags} onChange={(v) => set({ flags: v as Flag[] })}>
              {(inBid ? [...FLAGS, ...BID_FLAGS] : FLAGS).map((x) => <Checkbox key={x} value={x}>{flagName(x)}</Checkbox>)}
            </CheckboxGroup>
          </div>
          {inBid && (
            <div className="fx-pop-group">
              <h4>Documents</h4>
              <CheckboxGroup aria-label="Documents" value={f.docs.map(String)} onChange={(v) => set({ docs: v.map(Number) })}>
                {docs.map((d) => <Checkbox key={d.no} value={String(d.no)}>{`d${d.no} ${d.file_name}`}</Checkbox>)}
              </CheckboxGroup>
            </div>
          )}
          {inBid && (
            <div className="fx-pop-group">
              <h4>Levels</h4>
              <CheckboxGroup aria-label="Levels" value={f.levels.map(String)} onChange={(v) => set({ levels: v.map(Number) })}>
                {[1, 2, 3, 4].map((n) => <Checkbox key={n} value={String(n)}>{levelChip(n)}</Checkbox>)}
              </CheckboxGroup>
            </div>
          )}
          {pages > 1 && (
            <RangeSlider
              label="Pages"
              minValue={1}
              maxValue={pages}
              step={1}
              value={range}
              onChange={setRange}
              onChangeEnd={(r) => set(r.start === 1 && r.end === pages ? { pageFrom: null, pageTo: null } : { pageFrom: r.start, pageTo: r.end })}
            />
          )}
          <div className="fx-pop-group">
            <Switch isSelected={f.splitOnly} onChange={(v) => set({ splitOnly: v })}>Split votes only</Switch>
            <Switch isSelected={f.edited} onChange={(v) => set({ edited: v })}>Changed only</Switch>
            <Switch isSelected={f.includeDeleted} onChange={(v) => set({ includeDeleted: v })}>Show deleted</Switch>
          </div>
        </div>
      </Dialog>
    </DialogTrigger>
  );
}

export function FactsTab() {
  const { run, facts, factById, reloadAll, factsPreset, clearFactsPreset } = useRun();
  const docs = useBidDocs();
  const { inBid } = docs;
  const [filters, setFilters] = useState<FactsListFilters>(emptyFilters);
  const [query, setQuery] = useState('');
  const [size, setSize] = useState<number>(PAGE_SIZES[0]);
  const [page, setPage] = useState(1);
  const [adding, setAdding] = useState(false);
  const set = (p: Partial<FactsListFilters>) => setFilters((cur) => ({ ...cur, ...p }));

  const debQ = useDebounced(query, 250);
  const effective = useMemo(() => ({ ...filters, q: debQ }), [filters, debQ]);
  const key = JSON.stringify(effective);
  // `facts.data` changes after every write, so the list follows corrections.
  const list = useAsync((signal) => api.getFactsList(run, effective, signal), [run, key, facts.data]);
  useEffect(() => setPage(1), [key, size, run]);

  // A new run starts with fresh filters. Declared before the preset effect so a preset set at the
  // same moment (mount, or a run change) is applied on top of the reset and not wiped by it.
  const seeded = useRef('');
  useEffect(() => {
    setFilters(emptyFilters());
    setQuery('');
    seeded.current = '';
  }, [run]);
  // In a bid, replaced facts are hidden until the reader asks for them. The documents arrive with the facts, so this
  // runs once the run turns out to be a bid. It is declared before the preset effect so a preset still wins.
  useEffect(() => {
    if (!inBid || seeded.current === run) return;
    seeded.current = run;
    setFilters((cur) => ({ ...cur, hideReplaced: true }));
  }, [inBid, run]);

  // A preset from another page (e.g. the overview's "risks" link) replaces the filters.
  useEffect(() => {
    if (!factsPreset) return;
    const { q, ...rest } = factsPreset;
    setFilters({ ...emptyFilters(), hideReplaced: inBid, ...rest, q: '' });
    setQuery(q ?? '');
    clearFactsPreset();
  }, [factsPreset, clearFactsPreset, inBid]);

  const hiding = inBid && filters.hideReplaced;
  const entries = useMemo(() => {
    const all = list.data ? listEntries(list.data.items, factById) : [];
    return hiding ? withoutReplaced(all) : all;
  }, [list.data, factById, hiding]);
  const pg = paginate(entries, size, page);
  const allFacts = facts.data?.facts ?? [];
  const liveCount = allFacts.filter((f) => !f.deleted).length;
  const hasPostAward = useMemo(() => allFacts.some((f) => f.post_award || f.flags.includes('post-award')), [allFacts]);
  const totalPages = facts.data?.pages ?? 0;

  const header = (
    <PageHeader
      title="Facts"
      subtitle={facts.data ? (list.data && list.data.total !== liveCount ? `${list.data.total} of ${liveCount} facts` : `${liveCount} facts`) : undefined}
      actions={
        <>
          {inBid ? (
            <>
              <Button variant="secondary" elementType="a" href={api.factsCsvUrl(run, effective)} aria-label="Download CSV of the filtered facts, for the team">CSV for the team</Button>
              <Button variant="secondary" elementType="a" href={api.factsCsvUrl(run, effective, 'external')} aria-label="Download CSV of the filtered facts to share, without internal sources">CSV to share (no internal sources)</Button>
            </>
          ) : (
            <Button variant="secondary" elementType="a" href={api.factsCsvUrl(run, effective)} aria-label="Download CSV of the filtered facts">Download CSV</Button>
          )}
          <Button variant="accent" onPress={() => setAdding(true)}>Add fact</Button>
        </>
      }
    />
  );

  if (facts.loading && !facts.data) return <>{header}<Loading label="Loading facts" /></>;
  if (facts.error && !facts.data) {
    return (
      <>
        {header}
        <div className="fx-state"><strong>The facts could not be loaded</strong><span>{facts.error}</span><Button variant="secondary" onPress={() => void reloadAll()}>Try again</Button></div>
      </>
    );
  }

  const byCat = list.data?.by_category ?? {};
  const codes = [...CATEGORY_CODES.filter((c) => byCat[c] || filters.categories.includes(c)), ...Object.keys(byCat).filter((c) => !CATEGORY_CODES.includes(c as never) && byCat[c]).sort()];
  const nFacts = pg.slice.reduce((n, e) => n + e.facts.length, 0);
  const first = (pg.page - 1) * size + 1;

  // Active filters, as removable chips. Search and view have their own controls.
  const chips: { key: string; label: string; remove: () => void }[] = [];
  for (const c of filters.categories) chips.push({ key: `c${c}`, label: categoryName(c), remove: () => set({ categories: filters.categories.filter((x) => x !== c) }) });
  const statusActive = filters.statuses.length > 0 && !ALL_STATUSES.every((s) => filters.statuses.includes(s));
  if (statusActive) chips.push({ key: 'status', label: `Status: ${filters.statuses.map((s) => STATUS_LABEL[s]).join(', ')}`, remove: () => set({ statuses: [...ALL_STATUSES] }) });
  for (const x of filters.flags) chips.push({ key: `f${x}`, label: `Flag: ${x}`, remove: () => set({ flags: filters.flags.filter((y) => y !== x) }) });
  if (filters.pageFrom !== null && filters.pageTo !== null) chips.push({ key: 'pages', label: `Pages ${filters.pageFrom}-${filters.pageTo}`, remove: () => set({ pageFrom: null, pageTo: null }) });
  if (filters.splitOnly) chips.push({ key: 'split', label: 'Split votes only', remove: () => set({ splitOnly: false }) });
  if (filters.edited) chips.push({ key: 'edited', label: 'Changed only', remove: () => set({ edited: false }) });
  if (filters.includeDeleted) chips.push({ key: 'deleted', label: 'Showing deleted', remove: () => set({ includeDeleted: false }) });
  for (const n of filters.docs) {
    const d = docs.byNo.get(n);
    chips.push({ key: `d${n}`, label: `Document d${n}${d ? ` ${d.file_name}` : ''}`, remove: () => set({ docs: filters.docs.filter((x) => x !== n) }) });
  }
  for (const n of filters.levels) chips.push({ key: `l${n}`, label: `Level ${n}`, remove: () => set({ levels: filters.levels.filter((x) => x !== n) }) });
  const filterCount = (statusActive ? 1 : 0) + (filters.flags.length ? 1 : 0) + (filters.pageFrom !== null ? 1 : 0)
    + (filters.splitOnly ? 1 : 0) + (filters.edited ? 1 : 0) + (filters.includeDeleted ? 1 : 0)
    + (filters.docs.length ? 1 : 0) + (filters.levels.length ? 1 : 0);
  const clearAll = () => { setFilters((cur) => ({ ...emptyFilters(), view: cur.view, hideReplaced: cur.hideReplaced })); setQuery(''); };

  return (
    <div>
      {header}
      <div className="fx-toolbar">
        <div className="fx-toolbar-row">
          <div className="fx-search"><SearchField aria-label="Search facts" placeholder="Search facts" value={query} onChange={setQuery} width="100%" /></div>
          <CategoryMenu f={filters} set={set} byCat={byCat} codes={codes} />
          <ViewSwitch view={filters.view} onChange={(v: ViewName) => set({ view: v })} hasPostAward={hasPostAward} />
          <FiltersMenu f={filters} set={set} pages={totalPages} count={filterCount} />
          {inBid && <Switch isSelected={filters.hideReplaced} onChange={(v) => set({ hideReplaced: v })}>Hide replaced</Switch>}
        </div>
        {chips.length > 0 && (
          <div className="fx-chips" aria-label="Active filters">
            {chips.map((c) => (
              <button key={c.key} type="button" className="fx-fchip" aria-label={`Remove filter ${c.label}`} onClick={c.remove}>
                {c.label}<span className="x" aria-hidden>&times;</span>
              </button>
            ))}
            <button type="button" className="fx-clear" onClick={clearAll}>Clear all</button>
          </div>
        )}
      </div>
      {facts.error && <ErrorBox message={facts.error} onRetry={() => void reloadAll()} />}
      {list.error && (
        <div className="fx-error" role="alert"><span>{list.error}</span><Button variant="secondary" onPress={list.reload}>Try again</Button></div>
      )}
      {list.loading && !list.data ? (
        <Loading label="Loading the list" />
      ) : allFacts.length === 0 ? (
        <div className="fx-state"><strong>No facts yet</strong><span>This run has no facts.</span></div>
      ) : list.data && entries.length === 0 ? (
        <div className="fx-state">
          <strong>No facts match these filters</strong>
          <span>{hiding ? 'Try a different search, remove a filter, or turn off Hide replaced.' : 'Try a different search or remove a filter.'}</span>
          {(chips.length > 0 || query) && <Button variant="secondary" onPress={clearAll}>Clear all</Button>}
        </div>
      ) : list.data ? (
        <>
          <div className="fx-list" role="list" aria-label="Facts" aria-busy={list.loading} style={list.loading ? { opacity: 0.6 } : undefined}>
            {pg.slice.map((e) => (
              <div role="listitem" key={e.first.fact_id}>
                {e.kind === 'list' ? <GroupCard e={e} /> : e.kind === 'same' ? <SameRow e={e} /> : <FactRow f={e.first} stated={e.stated} />}
              </div>
            ))}
          </div>
          <div className="fx-pager">
            <label className="grp">
              Per page
              <select className="fx-select" value={size} onChange={(e) => setSize(Number(e.target.value))}>
                {PAGE_SIZES.map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
            </label>
            <span className="grp" aria-live="polite">
              {first}-{first + pg.slice.length - 1} of {entries.length} items{nFacts !== pg.slice.length ? ` (${nFacts} facts)` : ''}
            </span>
            {pg.pages > 1 && (
              <span className="grp">
                <Button variant="secondary" isDisabled={pg.page <= 1} onPress={() => setPage(pg.page - 1)}>Previous</Button>
                <span>Page {pg.page} of {pg.pages}</span>
                <Button variant="secondary" isDisabled={pg.page >= pg.pages} onPress={() => setPage(pg.page + 1)}>Next</Button>
              </span>
            )}
          </div>
        </>
      ) : null}
      <DialogContainer onDismiss={() => setAdding(false)}>
        {adding && <AddFactDialog onClose={() => setAdding(false)} />}
      </DialogContainer>
    </div>
  );
}
