import { useEffect, useMemo, useState, type CSSProperties } from 'react';
import { Button, Checkbox, CheckboxGroup, Dialog, DialogContainer, DialogTrigger, RangeSlider, SearchField, Switch } from '@adobe/react-spectrum';
import * as api from '../api';
import { emptyFilters, ALL_STATUSES, listEntries, paginate, PAGE_SIZES, type ListEntry } from '../factsQuery';
import { useAsync, useDebounced } from '../hooks';
import { useRun } from '../store';
import type { Fact, FactsListFilters, FactStatus, Flag, ViewName } from '../types';
import { CATEGORY_CODES, FLAGS } from '../types';
import { ErrorBox, Loading, ViewSwitch, firstPage } from './common';
import { AddFactDialog } from './FactDetail';
import { PageHeader } from './shell/PageHeader';
import { CatPill, FactTags, STATUS_LABEL, categoryName } from './facts/parts';
import './facts.css';

function FactRow({ f, stated = 1, pages }: { f: Fact; stated?: number; pages?: string }) {
  const { openFact, openFactId } = useRun();
  const label = pages ?? firstPage(f);
  return (
    <button
      type="button"
      className={`fx-row${f.deleted ? ' deleted' : ''}`}
      aria-current={openFactId === f.fact_id ? 'true' : undefined}
      aria-label={`Open fact ${f.fact_id}: ${f.text}`}
      onClick={() => openFact(f.fact_id)}
    >
      <CatPill code={f.category} />
      <span className="fx-text"><span className="fx-t">{f.text}</span><span className="fx-meta"><FactTags f={f} stated={stated} /></span></span>
      <span className="fx-pg">{label ? `p. ${label}` : ''}</span>
    </button>
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
              {FLAGS.map((x) => <Checkbox key={x} value={x}>{x}</Checkbox>)}
            </CheckboxGroup>
          </div>
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
  useEffect(() => {
    setFilters(emptyFilters());
    setQuery('');
  }, [run]);

  // A preset from another page (e.g. the overview's "risks" link) replaces the filters.
  useEffect(() => {
    if (!factsPreset) return;
    const { q, ...rest } = factsPreset;
    setFilters({ ...emptyFilters(), ...rest, q: '' });
    setQuery(q ?? '');
    clearFactsPreset();
  }, [factsPreset, clearFactsPreset]);

  const entries = useMemo(() => (list.data ? listEntries(list.data.items, factById) : []), [list.data, factById]);
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
          <Button variant="secondary" elementType="a" href={api.factsCsvUrl(run, effective)} aria-label="Download CSV of the filtered facts">Download CSV</Button>
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
  const filterCount = (statusActive ? 1 : 0) + (filters.flags.length ? 1 : 0) + (filters.pageFrom !== null ? 1 : 0)
    + (filters.splitOnly ? 1 : 0) + (filters.edited ? 1 : 0) + (filters.includeDeleted ? 1 : 0);
  const clearAll = () => { setFilters((cur) => ({ ...emptyFilters(), view: cur.view })); setQuery(''); };

  return (
    <div>
      {header}
      <div className="fx-toolbar">
        <div className="fx-toolbar-row">
          <div className="fx-search"><SearchField aria-label="Search facts" placeholder="Search facts" value={query} onChange={setQuery} width="100%" /></div>
          <CategoryMenu f={filters} set={set} byCat={byCat} codes={codes} />
          <ViewSwitch view={filters.view} onChange={(v: ViewName) => set({ view: v })} hasPostAward={hasPostAward} />
          <FiltersMenu f={filters} set={set} pages={totalPages} count={filterCount} />
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
          <span>Try a different search or remove a filter.</span>
          {(chips.length > 0 || query) && <Button variant="secondary" onPress={clearAll}>Clear all</Button>}
        </div>
      ) : list.data ? (
        <>
          <div className="fx-list" role="list" aria-label="Facts" aria-busy={list.loading} style={list.loading ? { opacity: 0.6 } : undefined}>
            {pg.slice.map((e) => (
              <div role="listitem" key={e.first.fact_id}>
                {e.kind === 'list' ? <GroupCard e={e} /> : <FactRow f={e.first} stated={e.stated} pages={e.kind === 'same' ? e.pages : undefined} />}
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
