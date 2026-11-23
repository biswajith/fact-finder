import { Fragment } from 'react';
import { citeDoc, citeLabel, isInternal, useBidDocs } from '../../bidDocs';
import { useRun } from '../../store';
import type { Citation } from '../../types';

const spoken = (c: Citation) => (c.speaker ? `${c.speaker}${c.page_label ? ` (${c.page_label})` : ''}:` : '');

/** The wording a fact rests on, from the stored citations (never typed by the model), with a link to open the page. */
export function SourceSnippet({ factId }: { factId: string }) {
  const { factById, conflicts, openFact } = useRun();
  const docs = useBidDocs();
  const f = factById.get(factId);
  if (!f || f.deleted) return null;
  const cites = f.citations;
  const first = cites[0];
  const texts = cites.filter((c) => c.text.trim());
  let header = '';
  if (first) {
    if (docs.inBid) {
      const no = citeDoc(first, docs)?.no ?? first.doc_no ?? 0;
      const file = citeDoc(first, docs)?.file_name ?? first.doc_id ?? '';
      const label = first.page_label || (first.page ? String(first.page) : '');
      const doc = [no ? `d${no}` : '', file].filter(Boolean).join(' ');
      header = [doc, label ? `${first.speaker ? 'time' : 'page'} ${label}` : ''].filter(Boolean).join(' · ') || citeLabel(first, docs);
    } else {
      header = [first.page_label ? `Page ${first.page_label}` : '', first.section].filter(Boolean).join(' · ');
    }
  }
  const internal = cites.length > 0 && cites.every(isInternal);
  const warning = f.flags.includes('replaced')
    ? 'This fact was replaced by a later document.'
    : f.stale
      ? `Check: ${f.stale}`
      : conflicts.data?.some((c) => c.status === 'open' && c.fact_ids.includes(factId))
        ? 'conflict'
        : '';
  return (
    <figure className="chat-source">
      <figcaption className="chat-source-head">
        <span className="chat-source-where">{header || 'Source'}{internal && <span className="cite-int">Internal</span>}</span>
        <button type="button" className="linkbtn" aria-label={`Open page of fact ${factId}`} onClick={() => openFact(factId)}>Open page</button>
      </figcaption>
      <div className="chat-source-body">
        {texts.length === 0 ? f.text : texts.map((c, i) => (
          <Fragment key={`${c.doc_id ?? ''}${c.id}${i}`}>
            {i > 0 && ' '}
            {c.speaker && <span className="muted">{spoken(c)} </span>}
            <mark>{c.text}</mark>
          </Fragment>
        ))}
      </div>
      {warning === 'conflict' ? (
        <div className="chat-source-warn">Open conflict on this fact. <a href="#/conflicts">See conflicts</a></div>
      ) : warning ? (
        <div className="chat-source-warn">{warning}</div>
      ) : null}
    </figure>
  );
}
