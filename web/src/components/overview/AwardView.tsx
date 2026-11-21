import { useMemo, useState } from 'react';
import type { Fact } from '../../types';
import { groupByCategory } from '../../overviewView';
import { CATEGORY_COLORS } from '../common';
import { PageCites } from '../CitationChip';
import { FactTags, categoryName } from '../facts/parts';
import { useRun } from '../../store';
import { CollapseProvider, ExpandCollapseAll, Section } from './Collapsible';
import '../facts.css';

const SHOWN = 8;

function FactLine({ f }: { f: Fact }) {
  const { openFact } = useRun();
  const shown = { ...f, flags: f.flags.filter((x) => x !== 'post-award') };
  return (
    <li className="ov-fact">
      <div className="ov-line">
        <button type="button" className="ov-open wrap-text" aria-label={`Open fact: ${f.text}`} onClick={() => openFact(f.fact_id)}>{f.text}</button>
        <PageCites ids={[f.fact_id]} />
      </div>
      <div className="ov-tags"><FactTags f={shown} /></div>
    </li>
  );
}

function CategoryCard({ code, facts }: { code: string; facts: Fact[] }) {
  const [all, setAll] = useState(false);
  const shown = all ? facts : facts.slice(0, SHOWN);
  return (
    <Section id={`award-${code}`} className="ov-card" title={categoryName(code)} color={CATEGORY_COLORS[code] ?? 'var(--cat-B)'} count={facts.length}>
      <ul className="ov-list">{shown.map((f) => <FactLine key={f.fact_id} f={f} />)}</ul>
      {facts.length > SHOWN && (
        <button type="button" className="ov-more" aria-expanded={all} onClick={() => setAll(!all)}>
          {all ? 'Show fewer' : `Show all ${facts.length}`}
        </button>
      )}
    </Section>
  );
}

/** What the winning bidder must do: the post-award facts, one collapsible card per category. */
export function AwardObligations({ facts, hasPostAward }: { facts: Fact[]; hasPostAward: boolean }) {
  const groups = useMemo(() => groupByCategory(facts), [facts]);
  if (groups.length === 0) {
    return (
      <div className="ov-empty-state" role="status">
        <strong>{hasPostAward ? 'No after-award obligations in the current facts' : 'This run marks nothing as after award'}</strong>
        <span>
          {hasPostAward
            ? 'Every after-award fact has been deleted.'
            : 'Runs made before facts were tagged post-award have none. Extract the RFP again to get this view.'}
        </span>
      </div>
    );
  }
  return (
    <CollapseProvider>
      <ExpandCollapseAll ids={groups.map((g) => `award-${g.code}`)} />
      <div className="ov-stack">
        {groups.map((g) => <CategoryCard key={g.code} code={g.code} facts={g.facts} />)}
      </div>
    </CollapseProvider>
  );
}
