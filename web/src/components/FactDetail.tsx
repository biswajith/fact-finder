import { useEffect, useMemo, useRef, useState } from 'react';
import { Button, Content, Dialog, Divider, Heading, Item, Picker } from '@adobe/react-spectrum';
import * as api from '../api';
import { citeDoc, citeLabel, isInternal, relationLines, replacedState, useBidDocs } from '../bidDocs';
import { useRun } from '../store';
import type { Citation, Fact, FactPatch } from '../types';
import { CATEGORY_NAMES } from '../types';
import { DocCite } from './CitationChip';
import { FactLink, formatTime } from './common';
import { FactForm, type FactFormValues } from './FactForm';
import { CatPill, FactTags } from './facts/parts';
import './facts.css';

const citeKey = (c: Citation) => `${c.doc_id ?? ''}|${c.id}`;

function PageImage({ run, factId, pages, doc }: { run: string; factId: string; pages: { page: number; label: string }[]; doc?: string }) {
  const [page, setPage] = useState(pages[0]?.page);
  const [state, setState] = useState<'loading' | 'ok' | 'missing'>('loading');
  useEffect(() => setState('loading'), [page, factId, run, doc]);
  if (page === undefined) return null;
  return (
    <div className="fx-page-img">
      {pages.length > 1 && (
        <Picker label="Page" selectedKey={String(page)} onSelectionChange={(k) => setPage(Number(k))}>
          {pages.map((p) => (
            <Item key={String(p.page)}>{`Page ${p.label}`}</Item>
          ))}
        </Picker>
      )}
      {state === 'missing' ? (
        <div className="muted">The page image is not available (this run has no PDF). Only the cited text is shown.</div>
      ) : (
        <>
          {state === 'loading' && <div className="muted">Loading page image...</div>}
          <img
            key={`${doc ?? ''}|${page}`}
            style={state === 'loading' ? { display: 'none' } : undefined}
            src={api.pageImageUrl(run, page, factId, doc)}
            alt={`PDF page ${pages.find((p) => p.page === page)?.label ?? page} with the cited text highlighted`}
            onLoad={() => setState('ok')}
            onError={() => setState('missing')}
          />
        </>
      )}
    </div>
  );
}

function FactBody({ fact, onClose }: { fact: Fact; onClose: () => void }) {
  const { run, act, setChatDraft, liveFacts, factById, openFact } = useRun();
  const docs = useBidDocs();
  const { inBid } = docs;
  // A point stated in several places: the facts of its "same" group, this one included.
  const stated = useMemo(
    () => (fact.group_id && fact.group_kind === 'same' ? liveFacts.filter((f) => f.group_id === fact.group_id) : []),
    [fact.group_id, fact.group_kind, liveFacts],
  );
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  // In a bid the page image belongs to one document: the one whose chip was pressed, if it has a PDF.
  const [openedKey, setOpenedKey] = useState('');
  const opened = fact.citations.find((c) => citeKey(c) === openedKey) ?? fact.citations[0] ?? null;
  const openedDoc = inBid && opened ? citeDoc(opened, docs) : undefined;
  const imageDoc = inBid ? (openedDoc?.has_pdf ? openedDoc.doc_id : undefined) : undefined;
  const pages = useMemo(() => {
    const seen = new Map<number, string>();
    for (const c of fact.citations) {
      if (inBid && c.doc_id !== imageDoc) continue;
      if (typeof c.page === 'number' && !seen.has(c.page)) seen.set(c.page, c.page_label || String(c.page));
    }
    return [...seen].map(([page, label]) => ({ page, label }));
  }, [fact.citations, inBid, imageDoc]);
  const replaced = inBid ? replacedState(fact) : null;
  const relations = inBid ? relationLines(fact) : [];
  const refText = (id: string, docId: string, unit: string) => {
    const f = id ? factById.get(id) : undefined;
    if (f) return f.text;
    const no = docs.byId.get(docId)?.no;
    return `${no ? `d${no} · ` : ''}${unit}`;
  };
  const reject = async (rid: string) => {
    setBusy(true);
    await act(() => api.rejectRelation(run, rid), 'Link rejected. Undo it on the Changes page.');
    setBusy(false);
  };

  const save = async (v: FactFormValues) => {
    const patch: FactPatch = {};
    if (v.text !== fact.text) patch.text = v.text;
    if (v.category !== fact.category) patch.category = v.category;
    if (v.note !== fact.note) patch.note = v.note;
    if ([...v.flags].sort().join() !== [...fact.flags].sort().join()) patch.flags = v.flags;
    if (Object.keys(patch).length === 0) return setEditing(false);
    if (v.reason.trim()) patch.reason = v.reason.trim();
    setBusy(true);
    const r = await act(() => api.patchFact(run, fact.fact_id, patch), 'Fact changed');
    setBusy(false);
    if (r) setEditing(false);
  };
  const del = async () => {
    setBusy(true);
    await act(() => api.deleteFact(run, fact.fact_id), 'Fact deleted');
    setBusy(false);
  };
  const restore = async () => {
    setBusy(true);
    await act(() => api.restoreFact(run, fact.fact_id), 'Fact restored to the extracted version');
    setBusy(false);
  };

  return (
    <>
      <div className="fx-panel-head">
        <CatPill code={fact.category} />
        <button type="button" className="fx-close" aria-label="Close" title="Close (Esc)" onClick={onClose}>&times;</button>
      </div>
      <div className="fx-panel-body">
        {editing ? (
          <FactForm fact={fact} busy={busy} onSubmit={save} onCancel={() => setEditing(false)} />
        ) : (
          <>
            <p className={`fx-big${fact.deleted ? ' deleted' : ''}`}>{fact.text}</p>
            <div className="fx-tags">
              <FactTags f={fact} stated={stated.length} />
            </div>
            {replaced && (
              <div className="fx-sec">
                <h3>{replaced.kind === 'by' ? 'Replaced by' : replaced.kind === 'removed' ? 'Removed by a later document' : 'Replaced'}</h3>
                {replaced.kind === 'by' && (
                  <div className="fx-replaced-by">
                    <button type="button" className="linkbtn" aria-label={`Open fact ${replaced.id}`} onClick={() => openFact(replaced.id)}>
                      {factById.get(replaced.id)?.text ?? replaced.id}
                    </button>
                  </div>
                )}
              </div>
            )}
            {inBid && fact.stale && <div className="fx-alert">Check: {fact.stale}</div>}
            {fact.deleted && <div className="fx-alert danger"><strong>This fact was deleted.</strong>Restore it to bring it back.</div>}
            {(fact.original?.text !== undefined || fact.original?.category !== undefined) && (
              <div className="fx-sec">
                <h3>As first extracted</h3>
                {fact.original?.text !== undefined && <div className="wrap-text old">{fact.original.text}</div>}
                {fact.original?.category !== undefined && <div className="muted">Category: {CATEGORY_NAMES[fact.original.category]}</div>}
              </div>
            )}
            {fact.note && <div className="fx-sec"><h3>Note</h3><div className="fx-note">{fact.note}</div></div>}
            {fact.problems.length > 0 && (
              <div className="fx-alert">
                <strong>Needs review</strong>
                <ul>{fact.problems.map((p, i) => <li key={i}>{p}</li>)}</ul>
              </div>
            )}
            {fact.resolution && (
              <div className="fx-sec">
                <h3>You decided</h3>
                <div className="wrap-text">{fact.resolution.text}{fact.resolution.at ? ` (${formatTime(fact.resolution.at)})` : ''}</div>
              </div>
            )}
            {fact.conflicts.length > 0 && (
              <div className="fx-sec">
                <h3>Contradicted by</h3>
                <div className="row">
                  {fact.conflicts.map((id) => <FactLink key={id} id={id} />)}
                </div>
              </div>
            )}
            {stated.length > 1 && (
              <div className="muted wrap-text">
                This point is stated {stated.length} times, on pages {[...new Set(stated.flatMap((f) => f.citations.map((c) => c.page_label || String(c.page))))].join('; ')}.
              </div>
            )}
            {relations.length > 0 && (
              <div className="fx-sec">
                <h3>Links to other documents</h3>
                {relations.map((r) => (
                  <div className="fx-rel" key={`${r.id}|${r.otherFactId}|${r.otherDocId}|${r.otherUnit}`}>
                    <span className="w">{r.words}</span>
                    <span className="o">
                      {r.otherFactId && factById.get(r.otherFactId) ? (
                        <button type="button" className="linkbtn" aria-label={`Open fact ${r.otherFactId}`} onClick={() => openFact(r.otherFactId)}>
                          {refText(r.otherFactId, r.otherDocId, r.otherUnit)}
                        </button>
                      ) : refText(r.otherFactId, r.otherDocId, r.otherUnit)}
                    </span>
                    <Button variant="secondary" isDisabled={busy} onPress={() => void reject(r.id)} aria-label={`Reject link: ${r.words} ${refText(r.otherFactId, r.otherDocId, r.otherUnit)}`}>Reject</Button>
                  </div>
                ))}
              </div>
            )}
            <div className="fx-sec">
              <h3>Where it comes from</h3>
              {fact.citations.length === 0 && <div className="muted">No citation.</div>}
              {inBid && fact.citations.length > 0 && (
                <div className="fx-cites" style={{ marginBottom: 8 }}>
                  {fact.citations.map((c) => (
                    <DocCite key={citeKey(c)} c={c} pressed={opened !== null && citeKey(opened) === citeKey(c)} onPress={() => setOpenedKey(citeKey(c))} />
                  ))}
                </div>
              )}
              {fact.citations.map((c) => (
                <blockquote key={citeKey(c)} className={`fx-quote${inBid && opened !== null && citeKey(opened) === citeKey(c) ? ' on' : ''}`}>
                  {inBid ? (
                    <div className="src">
                      {citeLabel(c, docs)}{c.section ? ` · ${c.section}` : ''}{isInternal(c) ? ' · Internal' : ''}
                    </div>
                  ) : (
                    <div className="src">Page {c.page_label || c.page}{c.section ? ` · ${c.section}` : ''}</div>
                  )}
                  <div className="q">{c.text}</div>
                </blockquote>
              ))}
            </div>
            {fact.unresolved_ids.length > 0 && (
              <div className="fx-alert">
                <strong>Unknown cited IDs</strong>
                The model cited IDs that are not in the document: {fact.unresolved_ids.join(', ')}
              </div>
            )}
            {pages.length > 0 && (!inBid || imageDoc) && <PageImage key={`${fact.fact_id}|${imageDoc ?? ''}`} run={run} factId={fact.fact_id} pages={pages} doc={imageDoc} />}
            <details className="fx-details">
              <summary>Details</summary>
              <div className="muted wrap-text">
                ID {fact.fact_id}{fact.source_call ? ` · source call ${fact.source_call}` : ''}
              </div>
            </details>
          </>
        )}
      </div>
      {!editing && (
        <div className="fx-panel-foot">
          <Button variant="secondary" isDisabled={busy} onPress={() => { setChatDraft(`About [${fact.fact_id}]: `); onClose(); }}>Ask in chat</Button>
          {fact.deleted ? (
            <Button variant="accent" isDisabled={busy} onPress={restore}>Restore</Button>
          ) : (
            <>
              {fact.edited && fact.origin === 'extracted' && <Button variant="secondary" isDisabled={busy} onPress={restore}>Restore</Button>}
              <Button variant="negative" isDisabled={busy} onPress={del}>Delete</Button>
              <Button variant="accent" isDisabled={busy} onPress={() => setEditing(true)}>Edit</Button>
            </>
          )}
        </div>
      )}
    </>
  );
}

/** Right-hand side panel showing the fact whose id is `openFactId` in the run context. */
export function FactDetail() {
  const { openFactId, openFact, factById, facts } = useRun();
  const fact = openFactId ? factById.get(openFactId) : undefined;
  const close = () => openFact(null);
  const ref = useRef<HTMLElement>(null);
  const open = openFactId !== null;

  // Escape closes the panel, unless a dialog or popover (add-fact, filters) is open above it.
  useEffect(() => {
    if (!open) return;
    const on = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || e.defaultPrevented) return;
      if (document.querySelector('[role="dialog"], [role="alertdialog"]')) return;
      openFact(null);
    };
    window.addEventListener('keydown', on);
    return () => window.removeEventListener('keydown', on);
  }, [open, openFact]);
  // Move focus into the panel when it opens.
  useEffect(() => {
    if (open && !ref.current?.contains(document.activeElement)) ref.current?.focus();
  }, [open]);

  if (!openFactId) return null;
  return (
    <aside ref={ref} className="fx-panel" tabIndex={-1} aria-label={`Fact ${openFactId}`}>
      {fact ? (
        <FactBody key={fact.fact_id} fact={fact} onClose={close} />
      ) : (
        <>
          <div className="fx-panel-head">
            <strong>Fact {openFactId}</strong>
            <button type="button" className="fx-close" aria-label="Close" onClick={close}>&times;</button>
          </div>
          <div className="fx-panel-body">
            <div className="fx-state">{facts.loading ? 'Loading...' : 'This fact is not in the current run.'}</div>
          </div>
        </>
      )}
    </aside>
  );
}

/** Dialog for adding a new fact. */
export function AddFactDialog({ onClose }: { onClose: () => void }) {
  const { run, act, openFact } = useRun();
  const [busy, setBusy] = useState(false);
  const submit = async (v: FactFormValues) => {
    setBusy(true);
    const ids = v.citationIds.split(',').map((s) => s.trim()).filter(Boolean);
    const r = await act(
      () => api.addFact(run, { category: v.category, text: v.text, flags: v.flags, note: v.note || undefined, citation_ids: ids.length ? ids : undefined }),
      'Fact added',
    );
    setBusy(false);
    if (r) {
      onClose();
      openFact(r.fact_id);
    }
  };
  return (
    <Dialog size="M" aria-label="Add a fact">
      <Heading>Add a fact</Heading>
      <Divider />
      <Content>
        <FactForm busy={busy} onSubmit={submit} onCancel={onClose} />
      </Content>
    </Dialog>
  );
}
