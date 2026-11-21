import { useState } from 'react';
import { Button } from '@adobe/react-spectrum';
import * as api from '../api';
import { useRun } from '../store';
import type { ViewName } from '../types';
import { ErrorBox, Loading, ViewSwitch } from './common';
import { Glance, buyerLine, needsSummary, useOverview } from './Glance';
import { PageHeader } from './shell/PageHeader';
import './overview.css';

export function SummaryTab() {
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
          <Glance ov={ov} view={view} />
        </>
      )}
    </div>
  );
}
