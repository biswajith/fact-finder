import { useEffect, useMemo, useState, type CSSProperties } from 'react';
import {
  ActionGroup, Badge, Button, Checkbox, CheckboxGroup, Dialog, DialogContainer, DialogTrigger, Item, Radio, RadioGroup,
  RangeSlider, SearchField, Switch,
} from '@adobe/react-spectrum';
import * as api from '../api';
import { emptyFilters, ALL_STATUSES, listEntries, paginate, PAGE_SIZES, type ListEntry } from '../factsQuery';
import { useAsync, useDebounced } from '../hooks';
import { useRun } from '../store';
import type { Fact, FactsListFilters, FactStatus, Flag, ViewName } from '../types';
import { CATEGORY_CODES, CATEGORY_NAMES, FLAGS } from '../types';
import { CATEGORY_COLORS, CategoryChip, Empty, ErrorBox, FlagBadges, Loading, PageChip, ViewSwitch, firstPage } from './common';
import { AddFactDialog } from './FactDetail';

const STATUS_LABEL: Record<FactStatus, string> = { valid: 'valid', needs_review: 'needs review', conflict: 'conflict' };

function FactRow({ f, stated = 1, pages }: { f: Fact; stated?: number; pages?: string }) {
  const { openFact } = useRun();
  const label = pages ?? firstPage(f);
  return (
    <button type="button" className={`fact-row${f.deleted ? ' deleted' : ''}`} aria-label={`Open fact ${f.fact_id}: ${f.text}`} onClick={() => openFact(f.fact_id)}>
      <CategoryChip code={f.category} />
      <span className="fact-text wrap-text">{f.text}</span>
      <span className="fact-meta">
        {f.also && <Badge variant="neutral">also {CATEGORY_NAMES[f.also as keyof typeof CATEGORY_NAMES] ?? f.also}</Badge>}
        {f.split && <Badge variant="yellow">split vote{f.agreement ? ` ${f.agreement}` : ''}</Badge>}
        <FlagBadges flags={f.flags} />
        {f.status !== 'valid' && <Badge variant={f.status === 'conflict' ? 'negative' : 'yellow'}>{STATUS_LABEL[f.status] ?? f.status}</Badge>}
        {stated > 1 && <Badge variant="neutral">stated {stated} times</Badge>}
        {f.deleted ? <Badge variant="neutral">Deleted</Badge> : f.origin === 'user' ? <Badge variant="indigo">Added</Badge> : f.edited ? <Badge variant="info">Changed</Badge> : null}
      </span>
      <span className="muted">{label ? `p. ${label}` : ''}</span>
    </button>
  );
}

function GroupCard({ e }: { e: ListEntry }) {
  const { openFactId } = useRun();
  const inside = openFactId !== null && e.facts.some((f) => f.fact_id === openFactId);
  return (
    <details className="group-row" style={{ '--c': CATEGORY_COLORS[e.first.category] ?? '#64748b' } as CSSProperties} open={inside || undefined}>
      <summary aria-label={`${e.title}, ${e.facts.length} items. Show or hide the items`}>
        <CategoryChip code={e.first.category} />
        <span className="wrap-text" style={{ flex: 1 }}>{e.title}</span>
        <Badge variant="neutral">{e.facts.length} items</Badge>
        <PageChip page={e.pages} />
      </summary>
      {e.facts.map((f) => (
        <div role="listitem" key={f.fact_id}><FactRow f={f} /></div>
      ))}
    </details>
  );
}

function MoreFilters({ f, set, pages }: { f: FactsListFilters; set: (p: Partial<FactsListFilters>) => void; pages: number }) {
  const [range, setRange] = useState({ start: f.pageFrom ?? 1, end: f.pageTo ?? Math.max(1, pages) });
  useEffect(() => setRange({ start: f.pageFrom ?? 1, end: f.pageTo ?? Math.max(1, pages) }), [f.pageFrom, f.pageTo, pages]);
  return (
    <DialogTrigger type="popover">
      <Button variant="secondary" aria-label="More filters">More filters</Button>
      <Dialog aria-label="More filters">
        <div className="popover-body">
          <CheckboxGroup label="Status" value={f.statuses} onChange={(v) => set({ statuses: v as FactStatus[] })}>
            {ALL_STATUSES.map((s) => <Checkbox key={s} value={s}>{STATUS_LABEL[s]}</Checkbox>)}
          </CheckboxGroup>
          <CheckboxGroup label="Flags (any of)" value={f.flags} onChange={(v) => set({ flags: v as Flag[] })}>
            {FLAGS.map((x) => <Checkbox key={x} value={x}>{x}</Checkbox>)}
          </CheckboxGroup>
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
          <Switch isSelected={f.splitOnly} onChange={(v) => set({ splitOnly: v })}>Split votes only</Switch>
          <div className="muted">Split votes: facts whose labelling votes did not all agree on the code.</div>
        </div>
      </Dialog>
    </DialogTrigger>
  );
}

export function FactsTab() {
  const { run, facts, reloadAll } = useRun();
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

  // A new run starts with fresh filters.
  useEffect(() => {
    setFilters(emptyFilters());
    setQuery('');
  }, [run]);

  const entries = useMemo(() => (list.data ? listEntries(list.data.items, list.data.facts) : []), [list.data]);
  const pg = paginate(entries, size, page);
  const allFacts = facts.data?.facts ?? [];
  const hasPostAward = useMemo(() => allFacts.some((f) => f.post_award || f.flags.includes('post-award')), [allFacts]);

  if (facts.loading && !facts.data) return <Loading label="Loading facts" />;
  if (facts.error && !facts.data) return <ErrorBox message={facts.error} onRetry={() => void reloadAll()} />;

  const byCat = list.data?.by_category ?? {};
  const codes = [...CATEGORY_CODES.filter((c) => byCat[c]), ...Object.keys(byCat).filter((c) => !CATEGORY_CODES.includes(c as never) && byCat[c]).sort()];
  const name = (c: string) => CATEGORY_NAMES[c as keyof typeof CATEGORY_NAMES] ?? c;
  const nFacts = pg.slice.reduce((n, e) => n + e.facts.length, 0);
  const grouped = list.data ? list.data.total - entries.length : 0;
  const first = (pg.page - 1) * size + 1;

  return (
    <div className="panel">
      {facts.error && <ErrorBox message={facts.error} onRetry={() => void reloadAll()} />}
      <ViewSwitch view={filters.view} onChange={(v: ViewName) => set({ view: v })} hasPostAward={hasPostAward} />
      <div className="row">
        <SearchField label="Search facts" value={query} onChange={setQuery} width="size-3600" />
        <MoreFilters f={filters} set={set} pages={facts.data?.pages ?? 0} />
        <RadioGroup label="Facts per page" orientation="horizontal" value={String(size)} onChange={(v) => setSize(Number(v))}>
          {PAGE_SIZES.map((n) => <Radio key={n} value={String(n)}>{String(n)}</Radio>)}
        </RadioGroup>
        <Switch isSelected={filters.edited} onChange={(v) => set({ edited: v })}>Changed only</Switch>
        <Switch isSelected={filters.includeDeleted} onChange={(v) => set({ includeDeleted: v })}>Show deleted</Switch>
        <span style={{ flex: 1 }} />
        <Button variant="secondary" elementType="a" href={api.factsCsvUrl(run, effective)} aria-label="Download CSV of the filtered facts">
          Download CSV
        </Button>
        <Button variant="accent" onPress={() => setAdding(true)}>Add fact</Button>
      </div>
      <ActionGroup
        aria-label="Filter by category"
        selectionMode="multiple"
        overflowMode="wrap"
        selectedKeys={filters.categories}
        onSelectionChange={(k) => set({ categories: [...k].map(String) })}
      >
        {codes.map((c) => (
          <Item key={c} aria-label={`${name(c)}, ${byCat[c]}`}>{`${name(c)} (${byCat[c]})`}</Item>
        ))}
      </ActionGroup>
      {list.error && <ErrorBox message={list.error} onRetry={list.reload} />}
      {list.loading && !list.data ? (
        <Loading label="Loading the list" />
      ) : allFacts.length === 0 ? (
        <Empty>This run has no facts.</Empty>
      ) : list.data && entries.length === 0 ? (
        <Empty>No facts match these filters.</Empty>
      ) : list.data ? (
        <>
          <div className="muted" aria-live="polite">
            {list.data.total} of {allFacts.filter((f) => !f.deleted).length} facts{grouped > 0 ? `, shown as ${entries.length} items` : ''}
          </div>
          <div role="list" aria-label="Facts" aria-busy={list.loading} style={list.loading ? { opacity: 0.6 } : undefined}>
            {pg.slice.map((e) =>
              e.kind === 'list' ? (
                <div role="listitem" key={e.first.fact_id}><GroupCard e={e} /></div>
              ) : (
                <div role="listitem" key={e.first.fact_id}><FactRow f={e.first} stated={e.stated} pages={e.kind === 'same' ? e.pages : undefined} /></div>
              ),
            )}
          </div>
        </>
      ) : null}
      {pg.pages > 1 && (
        <div className="row" style={{ justifyContent: 'center' }}>
          <Button variant="secondary" isDisabled={pg.page <= 1} onPress={() => setPage(pg.page - 1)}>Previous</Button>
          <span aria-live="polite">
            {first}-{first + pg.slice.length - 1} of {entries.length} items · page {pg.page} of {pg.pages}{nFacts !== pg.slice.length ? ` (${nFacts} facts)` : ''}
          </span>
          <Button variant="secondary" isDisabled={pg.page >= pg.pages} onPress={() => setPage(pg.page + 1)}>Next</Button>
        </div>
      )}
      <DialogContainer onDismiss={() => setAdding(false)}>
        {adding && <AddFactDialog onClose={() => setAdding(false)} />}
      </DialogContainer>
    </div>
  );
}
