import { useEffect, useMemo, useState } from 'react';
import { Button, ButtonGroup, Content, Dialog, DialogContainer, Divider, Heading, InlineAlert, Item, Picker } from '@adobe/react-spectrum';
import * as api from '../api';
import { useRun } from '../store';
import type { Fact, FactPatch } from '../types';
import { CATEGORY_NAMES } from '../types';
import { CategoryChip, FlagBadges, formatTime } from './common';
import { FactForm, type FactFormValues } from './FactForm';

function PageImage({ run, factId, pages }: { run: string; factId: string; pages: { page: number; label: string }[] }) {
  const [page, setPage] = useState(pages[0]?.page);
  const [state, setState] = useState<'loading' | 'ok' | 'missing'>('loading');
  useEffect(() => setState('loading'), [page, factId, run]);
  if (page === undefined) return null;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
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
            key={`${page}`}
            className="page-img"
            style={state === 'loading' ? { display: 'none' } : undefined}
            src={api.pageImageUrl(run, page, factId)}
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
  const { run, act, setChatDraft, openFact, liveFacts } = useRun();
  // A point stated in several places: the facts of its "same" group, this one included.
  const stated = useMemo(
    () => (fact.group_id && fact.group_kind === 'same' ? liveFacts.filter((f) => f.group_id === fact.group_id) : []),
    [fact.group_id, fact.group_kind, liveFacts],
  );
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const pages = useMemo(() => {
    const seen = new Map<number, string>();
    for (const c of fact.citations) if (!seen.has(c.page)) seen.set(c.page, c.page_label || String(c.page));
    return [...seen].map(([page, label]) => ({ page, label }));
  }, [fact.citations]);

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
      <Heading>
        <span style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}>
          <CategoryChip code={fact.category} /> {CATEGORY_NAMES[fact.category]}
        </span>
      </Heading>
      <Divider />
      <Content>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {editing ? (
            <FactForm fact={fact} busy={busy} onSubmit={save} onCancel={() => setEditing(false)} />
          ) : (
            <>
              <div className="wrap-text" style={{ fontSize: 16 }}>{fact.text}</div>
              {fact.deleted && <div><strong>This fact was deleted.</strong></div>}
              {fact.original?.text !== undefined && (
                <div className="muted wrap-text">As first extracted: <span className="old">{fact.original.text}</span></div>
              )}
              {fact.original?.category !== undefined && (
                <div className="muted">First extracted as: {CATEGORY_NAMES[fact.original.category]}</div>
              )}
              <div className="row">
                <FlagBadges flags={fact.flags} />
                {fact.edited && <span className="muted">Changed</span>}
                {fact.origin === 'user' && <span className="muted">Added by you</span>}
                <span className="muted">Status: {fact.status.replace('_', ' ')}</span>
                {fact.source_call && <span className="muted">Source call: {fact.source_call}</span>}
                {fact.split && <span className="muted">Split vote{fact.agreement ? ` ${fact.agreement}` : ''}</span>}
              </div>
              {fact.note && <div className="wrap-text"><strong>Note: </strong>{fact.note}</div>}
              {fact.problems.length > 0 && (
                <InlineAlert variant="notice">
                  <Heading>Needs review</Heading>
                  <Content>
                    <ul style={{ margin: 0, paddingLeft: 18 }}>
                      {fact.problems.map((p, i) => <li key={i} className="wrap-text">{p}</li>)}
                    </ul>
                  </Content>
                </InlineAlert>
              )}
              {fact.resolution && (
                <div className="wrap-text"><strong>You decided: </strong>{fact.resolution.text}{fact.resolution.at ? ` (${formatTime(fact.resolution.at)})` : ''}</div>
              )}
              {fact.conflicts.length > 0 && (
                <div className="row muted">
                  Contradicted by:{' '}
                  {fact.conflicts.map((id) => (
                    <button key={id} type="button" className="linkbtn" aria-label={`Open fact ${id}`} onClick={() => openFact(id)}>{id}</button>
                  ))}
                </div>
              )}
              <div>
                <strong>Where it comes from</strong>
                {fact.citations.length === 0 && <div className="muted">No citation.</div>}
                {fact.citations.map((c) => (
                  <div key={c.id} className="quote">
                    <div className="muted">Page {c.page_label || c.page}{c.section ? ` · ${c.section}` : ''}</div>
                    <div className="wrap-text">{c.text}</div>
                  </div>
                ))}
              </div>
              {fact.unresolved_ids.length > 0 && (
                <InlineAlert variant="notice">
                  <Heading>Unknown cited IDs</Heading>
                  <Content><span className="wrap-text">The model cited IDs that are not in the document: {fact.unresolved_ids.join(', ')}</span></Content>
                </InlineAlert>
              )}
              {stated.length > 1 && (
                <div className="muted wrap-text">
                  This point is stated {stated.length} times, on pages {[...new Set(stated.flatMap((f) => f.citations.map((c) => c.page_label || String(c.page))))].join('; ')}.
                </div>
              )}
              {pages.length > 0 && <PageImage key={fact.fact_id} run={run} factId={fact.fact_id} pages={pages} />}
            </>
          )}
        </div>
      </Content>
      {!editing && (
        <ButtonGroup>
          <Button variant="secondary" onPress={onClose}>Close</Button>
          <Button variant="secondary" isDisabled={busy} onPress={() => { setChatDraft(`About [${fact.fact_id}]: `); onClose(); }}>
            Ask in chat
          </Button>
          {fact.deleted ? (
            <Button variant="accent" isDisabled={busy} onPress={restore}>Restore</Button>
          ) : (
            <>
              {(fact.edited) && fact.origin === 'extracted' && (
                <Button variant="secondary" isDisabled={busy} onPress={restore}>Restore</Button>
              )}
              <Button variant="negative" isDisabled={busy} onPress={del}>Delete</Button>
              <Button variant="accent" isDisabled={busy} onPress={() => setEditing(true)}>Edit</Button>
            </>
          )}
        </ButtonGroup>
      )}
    </>
  );
}

/** Dialog that shows the fact whose id is `openFactId` in the run context. */
export function FactDetail() {
  const { openFactId, openFact, factById, facts } = useRun();
  const fact = openFactId ? factById.get(openFactId) : undefined;
  const close = () => openFact(null);
  return (
    <DialogContainer onDismiss={close} type="modal" isDismissable>
      {openFactId && (
        <Dialog size="L" aria-label={`Fact ${openFactId}`}>
          {fact ? (
            <FactBody key={fact.fact_id} fact={fact} onClose={close} />
          ) : (
            <>
              <Heading>Fact {openFactId}</Heading>
              <Divider />
              <Content>{facts.loading ? 'Loading...' : 'This fact is not in the current run.'}</Content>
              <ButtonGroup><Button variant="secondary" onPress={close}>Close</Button></ButtonGroup>
            </>
          )}
        </Dialog>
      )}
    </DialogContainer>
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
