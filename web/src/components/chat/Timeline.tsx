import * as api from '../../api';
import { useAsync } from '../../hooks';
import { useRun } from '../../store';
import type { TimelineRow } from '../../types';
import { CiteChip } from '../CitationChip';

function Row({ r }: { r: TimelineRow }) {
  return (
    <li className={`chat-timeline-row${r.replaced ? ' replaced' : ''}`}>
      <span className="chat-timeline-when">{r.label ? `${r.label}${r.time ? `, ${r.time}` : ''}` : ''}</span>
      <span className="chat-timeline-dot" aria-hidden />
      <span className="chat-timeline-what">
        <span className="chat-timeline-text">{r.text}</span> <CiteChip id={r.fact_id} />
      </span>
    </li>
  );
}

/** The chosen facts on a date line. The dates come from the server, read from each stored fact's text. */
export function Timeline({ factIds }: { factIds: string[] }) {
  const { run, factById } = useRun();
  const known = factIds.filter((id) => {
    const f = factById.get(id);
    return f && !f.deleted;
  });
  const key = known.join(',');
  const res = useAsync((signal) => api.getTimeline(run, known, signal), [run, key], known.length > 0);
  if (known.length === 0 || res.error) return null;
  if (!res.data) return <div className="muted">Loading dates...</div>;
  const dated = res.data.rows.filter((r) => r.date);
  const undated = res.data.rows.filter((r) => !r.date);
  if (!dated.length && !undated.length) return null;
  return (
    <div className="chat-timeline">
      {dated.length > 0 && <ol className="chat-timeline-list">{dated.map((r) => <Row key={r.fact_id} r={r} />)}</ol>}
      {undated.length > 0 && (
        <>
          <div className="chat-timeline-sub muted">No fixed date</div>
          <ol className="chat-timeline-list">{undated.map((r) => <Row key={r.fact_id} r={r} />)}</ol>
        </>
      )}
    </div>
  );
}
