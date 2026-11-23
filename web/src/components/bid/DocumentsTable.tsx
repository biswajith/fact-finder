import { Fragment, useState } from 'react';
import { AlertDialog, Button, DialogTrigger, Item, NumberField, Picker, ProgressCircle } from '@adobe/react-spectrum';
import { canConfirm, levelLabel, missingWords, playbookLabel, rowsInOrder } from '../../bid';
import type { UploadItem } from '../../bidFlow';
import type { Bid, BidDocument, BidDocumentPatch, BidPlaybook, SpeakerSide } from '../../types';
import { SpeakersPanel } from './SpeakersPanel';

const STATUS: Record<string, { text: string; tone: string }> = {
  uploaded: { text: 'Needs confirming', tone: 'warn' },
  confirmed: { text: 'Confirmed', tone: 'info' },
  extracting: { text: 'Extracting', tone: 'info' },
  extracted: { text: 'Extracted', tone: 'ok' },
  failed: { text: 'Failed', tone: 'danger' },
};

interface Draft { playbook: string; issue_number: number | null; issue_date: string | null; previous: string | null }

function Reads({ playbook }: { playbook: BidPlaybook | undefined }) {
  if (!playbook) return <span className="muted">-</span>;
  return (
    <span className="pg-chips">
      <span className="pg-pill">{levelLabel(playbook)}</span>
      {playbook.visibility === 'internal' && <span className="pg-pill warn">Internal</span>}
    </span>
  );
}

function Row({ doc, bid, onPatch, onRemove, onSpeakers }: {
  doc: BidDocument;
  bid: Bid;
  onPatch: (no: number, body: BidDocumentPatch) => Promise<boolean>;
  onRemove: (no: number) => Promise<boolean>;
  onSpeakers: (no: number, speakers: { id: string; name: string; side: SpeakerSide }[]) => Promise<boolean>;
}) {
  const known = (name: string) => bid.playbooks.some((p) => p.name === name);
  const [draft, setDraft] = useState<Draft>(() => ({
    playbook: known(doc.playbook) ? doc.playbook : doc.proposed.playbook,
    issue_number: doc.issue_number ?? doc.proposed.issue_number,
    issue_date: doc.issue_date ?? doc.proposed.issue_date,
    previous: doc.previous,
  }));
  const [busy, setBusy] = useState(false);
  const extracted = !!doc.run || doc.status === 'extracted';
  const editable = !doc.confirmed && !extracted && doc.status !== 'extracting';
  const view = editable ? draft : { playbook: doc.playbook, issue_number: doc.issue_number, issue_date: doc.issue_date, previous: doc.previous };
  const pb = bid.playbooks.find((p) => p.name === view.playbook);
  const st = STATUS[doc.status] ?? { text: doc.status, tone: '' };
  const replaceable = bid.documents.filter((d) => d.no !== doc.no && (d.playbook === 'rfp' || d.playbook === 'reissued-rfp'));
  const set = (patch: Partial<Draft>) => setDraft((d) => ({ ...d, ...patch }));
  const run = async (fn: () => Promise<boolean>) => {
    setBusy(true);
    await fn();
    setBusy(false);
  };
  const replacesNo = bid.documents.find((d) => d.doc_id === view.previous)?.no;
  const isChange = pb?.role === 'change';
  const confirmBody = (): BidDocumentPatch => ({
    playbook: draft.playbook,
    issue_number: isChange ? draft.issue_number : null,
    issue_date: draft.issue_date,
    ...(draft.playbook === 'reissued-rfp' ? { previous: draft.previous } : {}),
    confirmed: true,
  });
  const words = missingWords(doc.missing);
  const remove = (
    <DialogTrigger>
      <Button variant="negative" style="outline" isDisabled={busy} aria-label={`Remove d${doc.no} ${doc.file_name}`}>Remove</Button>
      <AlertDialog title={`Remove d${doc.no}?`} variant="destructive" primaryActionLabel="Remove" cancelLabel="Keep"
        onPrimaryAction={() => void run(() => onRemove(doc.no))}>
        {doc.file_name} will be taken out of the bid. This cannot be undone.
      </AlertDialog>
    </DialogTrigger>
  );

  return (
    <Fragment>
      <tr>
        <td className="num"><strong>d{doc.no}</strong></td>
        <td className="wrap-text">
          {doc.file_name}{doc.pages ? <span className="muted"> · {doc.pages} p.</span> : null}
          <div><span className={`pg-pill ${st.tone}`} role="status">{st.text}</span></div>
        </td>
        <td>
          {editable ? (
            <div className="pg-cell">
              <Picker
                aria-label={`Type of d${doc.no}`}
                items={bid.playbooks}
                selectedKey={known(draft.playbook) ? draft.playbook : null}
                onSelectionChange={(k) => k != null && set({ playbook: String(k) })}
                width="size-2000"
              >
                {(p) => <Item key={p.name}>{playbookLabel(p.name)}</Item>}
              </Picker>
              {draft.playbook === doc.proposed.playbook && <span className="pg-tag">suggested</span>}
              {pb?.description && <span className="muted pg-help">{pb.description}</span>}
              {draft.playbook === 'reissued-rfp' && (
                <Picker
                  label="Replaces"
                  items={replaceable}
                  selectedKey={draft.previous}
                  onSelectionChange={(k) => k != null && set({ previous: String(k) })}
                  width="size-2000"
                  placeholder="(choose)"
                >
                  {(d) => <Item key={d.doc_id}>{`d${d.no} ${d.file_name}`}</Item>}
                </Picker>
              )}
            </div>
          ) : (
            <div>
              <span title={pb?.description}>{playbookLabel(doc.playbook)}</span>
              {doc.playbook === 'reissued-rfp' && doc.previous && <div className="muted">Replaces {replacesNo ? `d${replacesNo}` : doc.previous}</div>}
            </div>
          )}
        </td>
        <td>
          {editable && isChange ? (
            <NumberField aria-label={`Issue number of d${doc.no}`} minValue={1} step={1} value={draft.issue_number ?? NaN}
              onChange={(n) => set({ issue_number: Number.isNaN(n) ? null : n })} width="size-1200" />
          ) : doc.issue_number ?? <span className="muted">-</span>}
        </td>
        <td>
          {editable ? (
            <input type="date" className="pg-date" aria-label={`Issue date of d${doc.no}`} value={draft.issue_date ?? ''}
              onChange={(e) => set({ issue_date: e.target.value || null })} />
          ) : doc.issue_date ?? <span className="muted">-</span>}
        </td>
        <td><Reads playbook={pb} /></td>
        <td>
          <div className="pg-actions">
            {editable && (
              <Button variant="accent" isDisabled={busy || !canConfirm(draft, pb)} onPress={() => void run(() => onPatch(doc.no, confirmBody()))}>Confirm</Button>
            )}
            {doc.confirmed && !extracted && doc.status !== 'extracting' && (
              <>
                <Button variant="secondary" isDisabled={busy} onPress={() => void run(() => onPatch(doc.no, { confirmed: false }))}>Edit</Button>
                {remove}
              </>
            )}
            {!doc.confirmed && !extracted && remove}
          </div>
        </td>
      </tr>
      {(editable && doc.proposed.checked === false) && (
        <tr className="pg-sub"><td /><td colSpan={6} className="pg-note">The suggested number or date was not found in the document; check it.</td></tr>
      )}
      {words && !extracted && (
        <tr className="pg-sub"><td /><td colSpan={6} className="pg-note">{words}</td></tr>
      )}
      {doc.error && (
        <tr className="pg-sub"><td /><td colSpan={6} role="alert" className="pg-note bad wrap-text">{doc.error}</td></tr>
      )}
      {doc.speakers.length > 0 && (
        <tr className="pg-sub">
          <td />
          <td colSpan={6}>
            <SpeakersPanel
              key={doc.speakers.map((s) => `${s.id}|${s.name}|${s.side}|${s.proposed}`).join(';') + String(doc.speakers_confirmed)}
              doc={doc}
              onConfirm={(speakers) => onSpeakers(doc.no, speakers)}
            />
          </td>
        </tr>
      )}
    </Fragment>
  );
}

export function DocumentsTable({ bid, uploads, onDismiss, onPatch, onRemove }: {
  bid: Bid;
  uploads: UploadItem[];
  onDismiss: (key: number) => void;
  onPatch: (no: number, body: BidDocumentPatch) => Promise<boolean>;
  onRemove: (no: number) => Promise<boolean>;
}) {
  const rows = rowsInOrder(bid);
  const onSpeakers = (no: number, speakers: { id: string; name: string; side: SpeakerSide }[]) =>
    onPatch(no, { speakers, speakers_confirmed: true });
  return (
    <section className="pg-stack" aria-labelledby="docs-title">
      <h2 className="pg-h2" id="docs-title">Documents of this bid</h2>
      {rows.length === 0 && uploads.length === 0 ? (
        <div className="pg-empty"><strong>No documents yet</strong>Add the RFP and anything that goes with it above.</div>
      ) : (
        <div className="pg-table-wrap pg-docs">
          <table className="data-table" aria-label="Documents of this bid">
            <thead>
              <tr>
                <th scope="col">No.</th><th scope="col">File</th><th scope="col">Type</th><th scope="col">Issue no.</th>
                <th scope="col">Issue date</th><th scope="col">Reads as</th><th scope="col"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((d) => (
                <Row
                  key={`${d.no}-${d.confirmed}-${d.status}`}
                  doc={d}
                  bid={bid}
                  onPatch={onPatch}
                  onRemove={onRemove}
                  onSpeakers={onSpeakers}
                />
              ))}
              {uploads.map((u) => (
                <tr key={`u${u.key}`}>
                  <td />
                  <td className="wrap-text">{u.name}</td>
                  <td colSpan={4}>
                    {u.status === 'pending' ? (
                      <span className="row" role="status"><ProgressCircle aria-label={`Uploading ${u.name}`} isIndeterminate size="S" /> Uploading...</span>
                    ) : (
                      <span role="alert" className="wrap-text pg-bad">{u.error}</span>
                    )}
                  </td>
                  <td>{u.status === 'error' && <Button variant="secondary" onPress={() => onDismiss(u.key)} aria-label={`Dismiss ${u.name}`}>Dismiss</Button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="muted">Issue order decides which document wins, not upload order.</div>
    </section>
  );
}
