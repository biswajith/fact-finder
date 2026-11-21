import { useState } from 'react';
import { Badge, Button, InlineAlert, Heading, Content } from '@adobe/react-spectrum';
import * as api from '../api';
import { useRun } from '../store';
import type { SummarySection } from '../types';
import { CategoryChip, Empty, ErrorBox, FactLink, Loading, formatTime } from './common';
import { Glance } from './Glance';

function Section({ s }: { s: SummarySection }) {
  const { run, act, setSummaries, factById } = useRun();
  const [showMissing, setShowMissing] = useState(false);
  const never = s.generated_at === null;
  const busy = s.updating;

  const generate = async () => {
    const r = await act(() => api.generateSummaries(run, [s.key]));
    if (r) setSummaries(r);
  };
  const pin = async (ids: string[], pinned: boolean) => {
    const r = await act(() => api.pinFacts(run, ids, pinned), pinned ? 'Added to the summary list' : 'Removed from the summary list');
    if (r) setSummaries(r);
  };

  return (
    <section className="card" aria-label={s.title}>
      <div className="row">
        <h2 style={{ fontSize: 18, flex: 1 }}>{s.title}</h2>
        {s.stale && <Badge variant="yellow">Out of date</Badge>}
        {busy && <Badge variant="info">Updating</Badge>}
        <Button
          variant={never ? 'accent' : 'secondary'}
          isDisabled={busy}
          aria-label={`${never ? 'Generate' : 'Rebuild'} ${s.title}`}
          onPress={generate}
        >
          {never ? 'Generate' : 'Rebuild'}
        </Button>
      </div>
      <div className="muted">
        {s.fact_count} facts{s.generated_at ? ` · built ${formatTime(s.generated_at)}` : ''}
      </div>
      {s.error && (
        <InlineAlert variant="negative">
          <Heading>This section could not be built</Heading>
          <Content><span className="wrap-text">{s.error}</span></Content>
        </InlineAlert>
      )}
      {never ? (
        <div className="muted">Not built yet. Press Generate to write this summary from the {s.fact_count} facts.</div>
      ) : s.points.length === 0 ? (
        <div className="muted">The summary has no points.</div>
      ) : (
        <ul className="points">
          {s.points.map((p, i) => (
            <li key={i}>
              <span className="wrap-text">{p.text}</span>{' '}
              <span className="row" style={{ display: 'inline-flex', gap: 6 }}>
                {p.fact_ids.map((id) => <FactLink key={id} id={id} />)}
              </span>
            </li>
          ))}
        </ul>
      )}
      {s.pinned.length > 0 && (
        <div className="row muted">
          Always included:
          {s.pinned.map((id) => (
            <span key={id} className="row" style={{ gap: 4 }}>
              <FactLink id={id} />
              <button type="button" className="linkbtn" aria-label={`Stop including fact ${id}`} onClick={() => void pin([id], false)}>(remove)</button>
            </span>
          ))}
        </div>
      )}
      {!never && (
        <div>
          <Button variant="secondary" isQuiet onPress={() => setShowMissing(!showMissing)} aria-expanded={showMissing}>
            {showMissing ? 'Hide' : 'Show'}: In the facts, not in this summary ({s.uncovered.length})
          </Button>
          {showMissing && (
            <div style={{ marginTop: 8 }}>
              {s.uncovered.length === 0 && <div className="muted">Every fact in this section is covered.</div>}
              {s.uncovered.map((id) => {
                const f = factById.get(id);
                const pinned = s.pinned.includes(id);
                return (
                  <div key={id} className="row" style={{ padding: '4px 0', borderBottom: '1px solid var(--spectrum-global-color-gray-200)', flexWrap: 'nowrap' }}>
                    {f && <CategoryChip code={f.category} />}
                    <span className="wrap-text" style={{ flex: 1 }}>{f ? f.text : id}</span>
                    <FactLink id={id} label="Open" />
                    {pinned ? (
                      <Badge variant="info">Pinned</Badge>
                    ) : (
                      <Button variant="secondary" aria-label={`Add fact ${id} to summary`} onPress={() => void pin([id], true)}>
                        Add to summary
                      </Button>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

export function SummaryTab() {
  const { summaries, run, act, setSummaries, reloadAll } = useRun();
  const sections = summaries.data?.sections ?? [];
  const anyBusy = summaries.data?.updating ?? false;
  return (
    <div className="panel">
      <Glance />
      <div className="row">
        <h2 style={{ fontSize: 18, margin: 0 }}>Written summaries</h2>
        <span className="muted" style={{ flex: 1 }}>Each summary is written from the facts and rebuilt when its facts change.</span>
        <Button
          variant="accent"
          isDisabled={anyBusy || sections.length === 0}
          onPress={async () => {
            const r = await act(() => api.generateSummaries(run));
            if (r) setSummaries(r);
          }}
        >
          Generate all
        </Button>
      </div>
      {summaries.loading && !summaries.data ? (
        <Loading label="Loading summaries" />
      ) : summaries.error && !summaries.data ? (
        <ErrorBox message={summaries.error} onRetry={() => void reloadAll()} />
      ) : (
        <>
          {summaries.error && <ErrorBox message={summaries.error} onRetry={() => void reloadAll()} />}
          {sections.length === 0 ? <Empty>No summary sections.</Empty> : sections.map((s) => <Section key={s.key} s={s} />)}
        </>
      )}
    </div>
  );
}
