import { useEffect, useMemo, useState } from 'react';
import {
  ActionBar, ActionBarContainer, ActionButton, ActionGroup, ActionMenu, AlertDialog, Badge, Button, Cell, Column, Content, DatePicker, DialogContainer,
  DropZone, FileTrigger, Flex, Heading, IllustratedMessage, InlineAlert, Item, LabeledValue, Link, NumberField, Picker, ProgressBar, ProgressCircle,
  Row, StatusLight, TableBody, TableHeader, TableView, Text, ToastQueue, Tooltip, TooltipTrigger, Well,
} from '@adobe/react-spectrum';
import { parseDate } from '@internationalized/date';
import Close from '@spectrum-icons/workflow/Close';
import Delete from '@spectrum-icons/workflow/Delete';
import Document from '@spectrum-icons/workflow/Document';
import FileCSV from '@spectrum-icons/workflow/FileCSV';
import FileJson from '@spectrum-icons/workflow/FileJson';
import FilePDF from '@spectrum-icons/workflow/FilePDF';
import FileTxt from '@spectrum-icons/workflow/FileTxt';
import FileWord from '@spectrum-icons/workflow/FileWord';
import MagicWand from '@spectrum-icons/workflow/MagicWand';
import UploadToCloud from '@spectrum-icons/workflow/UploadToCloud';
import { ACCEPTED, DOC_TYPES, isAccepted, missing, sizeLabel, typeInfo, type Doc, type Format } from '../data';
import { useIntake } from '../store';

const ICON: Record<Format, typeof FilePDF> = { pdf: FilePDF, word: FileWord, sheet: FileCSV, json: FileJson, text: FileTxt };
const FORMAT_LABEL: Record<Format, string> = { pdf: 'PDF', word: 'Word', sheet: 'Spreadsheet', json: 'JSON', text: 'Text' };

export function FileBadge({ format }: { format: Format }) {
  const I = ICON[format] ?? Document;
  return <span className={`ftype ${format}`} aria-hidden><I size="S" /></span>;
}

function Confidence({ doc }: { doc: Doc }) {
  const p = doc.proposal;
  if (doc.type !== p.type) return <span className="confidence">Changed by you</span>;
  if (p.confidence === null) return <span className="confidence">Rules, no model</span>;
  const pct = Math.round(p.confidence * 100);
  return (
    <TooltipTrigger delay={200}>
      <ActionButton isQuiet UNSAFE_style={{ height: 'auto', padding: 0, minWidth: 0 }} aria-label={`Suggested by the model, ${pct}% sure`}>
        <span className="confidence"><MagicWand size="XS" /> {pct}%<span className={`bar${pct < 80 ? ' mid' : ''}`}><span style={{ width: `${pct}%` }} /></span></span>
      </ActionButton>
      <Tooltip>{p.evidence}</Tooltip>
    </TooltipTrigger>
  );
}

const WORKING: Partial<Record<Doc['phase'], string>> = { reading: 'Reading the text', classifying: 'Working out what it is', speakers: 'Finding who speaks' };

function Status({ doc }: { doc: Doc }) {
  if (doc.phase === 'uploading') return <ProgressBar aria-label={`Uploading ${doc.name}`} label="Uploading" value={doc.progress} size="S" width="size-1700" showValueLabel={false} />;
  if (WORKING[doc.phase]) {
    return <Flex alignItems="center" gap="size-100"><ProgressCircle size="S" isIndeterminate aria-label={WORKING[doc.phase]} /><span className="small">{WORKING[doc.phase]}</span></Flex>;
  }
  if (doc.phase === 'failed') return <StatusLight variant="negative">Could not read</StatusLight>;
  const gaps = missing(doc).filter((m) => m !== 'Speakers');
  if (doc.confirmed && gaps.length) return <StatusLight variant="negative">{`Needs ${gaps[0].toLowerCase()}`}</StatusLight>;
  if (doc.confirmed) return <StatusLight variant="positive">Confirmed</StatusLight>;
  if (gaps.length) return <StatusLight variant="notice">{`Check: ${gaps[0].toLowerCase()}`}</StatusLight>;
  return <StatusLight variant="info">Ready to confirm</StatusLight>;
}

type Filter = 'all' | 'review' | 'confirmed' | 'problems';

export function DocumentsStep() {
  const { s, addFiles, addSamples, confirm, remove, retry } = useIntake();
  const [selected, setSelected] = useState<Set<string> | 'all'>(new Set());
  const [open, setOpen] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>('all');
  const [refused, setRefused] = useState<string[]>([]);
  const [removing, setRemoving] = useState<string[] | null>(null);

  const take = (files: { name: string; size: number }[]) => {
    setRefused(files.filter((f) => !isAccepted(f.name)).map((f) => f.name));
    const ok = files.filter((f) => isAccepted(f.name));
    if (ok.length) addFiles(ok);
  };
  const docs = s.docs;
  const counts = {
    all: docs.length,
    review: docs.filter((d) => d.phase === 'review').length,
    confirmed: docs.filter((d) => d.confirmed).length,
    problems: docs.filter((d) => d.phase === 'failed' || (d.phase === 'review' && missing(d).some((m) => m !== 'Speakers'))).length,
  };
  const rows = useMemo(() => docs.filter((d) => filter === 'all' || (filter === 'review' && d.phase === 'review') || (filter === 'confirmed' && d.confirmed)
    || (filter === 'problems' && (d.phase === 'failed' || (d.phase === 'review' && missing(d).some((m) => m !== 'Speakers'))))), [docs, filter]);
  const ids = selected === 'all' ? rows.map((d) => d.id) : [...selected];
  const confirmable = ids.filter((id) => { const d = docs.find((x) => x.id === id); return d && d.phase === 'review'; });
  const readyAll = docs.filter((d) => d.phase === 'review' && missing(d).filter((m) => m !== 'Speakers').length === 0);
  const current = docs.find((d) => d.id === open) ?? null;

  const drop = (
    <DropZone
      isFilled={docs.length > 0}
      replaceMessage="Drop to add these documents"
      onDrop={async (e) => {
        const files = await Promise.all(e.items.filter((i) => i.kind === 'file').map(async (i) => (i.kind === 'file' ? await i.getFile() : null)));
        take(files.filter((f): f is File => !!f).map((f) => ({ name: f.name, size: f.size })));
      }}
      UNSAFE_style={{ width: '100%', boxSizing: 'border-box', minHeight: docs.length ? 0 : 220, padding: docs.length ? '4px 16px' : undefined }}
    >
      {docs.length === 0 ? (
        <IllustratedMessage>
          <UploadToCloud size="XXL" />
          <Heading>Drop the bid documents here</Heading>
          <Content>
            <Flex direction="column" alignItems="center" gap="size-150">
              <span>RFP, addenda, forms, call transcripts and deal notes. PDF, Word, Excel, CSV, JSON or text.</span>
              <Flex gap="size-100">
                <FileTrigger allowsMultiple acceptedFileTypes={ACCEPTED} onSelect={(l) => take(Array.from(l ?? []).map((f) => ({ name: f.name, size: f.size })))}>
                  <Button variant="accent">Browse files</Button>
                </FileTrigger>
                <Button variant="secondary" style="outline" onPress={addSamples}>Use sample documents</Button>
              </Flex>
              <Link><a href="/samples/albany-cctv-sample-bid.zip" download>Download the sample files</a></Link>
            </Flex>
          </Content>
        </IllustratedMessage>
      ) : (
        <Flex alignItems="center" gap="size-150" UNSAFE_style={{ padding: 12 }}>
          <UploadToCloud />
          <Text>Drop more files here, or</Text>
          <FileTrigger allowsMultiple acceptedFileTypes={ACCEPTED} onSelect={(l) => take(Array.from(l ?? []).map((f) => ({ name: f.name, size: f.size })))}>
            <Button variant="secondary" style="outline">Browse</Button>
          </FileTrigger>
          {!docs.some((d) => d.name.startsWith('RFP-2027-04')) && <Button variant="secondary" isQuiet onPress={addSamples}>Add the sample documents</Button>}
        </Flex>
      )}
    </DropZone>
  );

  return (
    <>
      <section className="card" aria-labelledby="docs-h">
        <Flex alignItems="start" gap="size-200">
          <div style={{ flex: 1 }}>
            <h2 id="docs-h">Documents</h2>
            <p className="lede">Add everything that belongs to this bid. Each file is read and the model proposes what it is; you confirm or correct it.</p>
          </div>
          {readyAll.length > 1 && s.mock.modelOn && (
            <Button variant="primary" style="outline" onPress={() => { confirm(readyAll.map((d) => d.id)); ToastQueue.positive(`${readyAll.length} documents confirmed`, { timeout: 3000 }); }}>
              <MagicWand />
              <Text>Accept {readyAll.length} suggestions</Text>
            </Button>
          )}
        </Flex>
        {!s.mock.modelOn && (
          <InlineAlert variant="notice" marginBottom="size-200">
            <Heading>The model is off</Heading>
            <Content>Without an API key, types are only guessed by simple rules and the speakers of a call cannot be found. Check every type before confirming.</Content>
          </InlineAlert>
        )}
        {drop}
        {refused.length > 0 && (
          <InlineAlert variant="negative" marginTop="size-150">
            <Heading>Not added</Heading>
            <Content>{refused.join(', ')}: this file type is not supported. Use PDF, Word, Excel, CSV, JSON or text.</Content>
          </InlineAlert>
        )}
      </section>

      {docs.length > 0 && (
        <section className="card" aria-label="Uploaded documents">
          <Flex alignItems="center" marginBottom="size-150" gap="size-200">
            <ActionGroup selectionMode="single" disallowEmptySelection selectedKeys={[filter]} onSelectionChange={(k) => setFilter([...k][0] as Filter)} density="compact" aria-label="Show">
              <Item key="all">{`All ${counts.all}`}</Item>
              <Item key="review">{`To review ${counts.review}`}</Item>
              <Item key="confirmed">{`Confirmed ${counts.confirmed}`}</Item>
              <Item key="problems">{`Problems ${counts.problems}`}</Item>
            </ActionGroup>
            <div style={{ flex: 1 }} />
            <span className="muted small">Select a row to see what the model read.</span>
          </Flex>
          <div className={`split${current ? ' open' : ''}`}>
            <ActionBarContainer height={Math.min(660, 72 + rows.length * 80)}>
              <TableView
                aria-label="Documents of this bid"
                selectionMode="multiple"
                selectedKeys={selected}
                onSelectionChange={(k) => setSelected(k === 'all' ? 'all' : new Set([...k].map(String)))}
                onAction={(k) => setOpen(String(k))}
                overflowMode="wrap"
                density="spacious"
                renderEmptyState={() => <div className="muted">Nothing here.</div>}
              >
                <TableHeader>
                  <Column key="file" width="2fr" minWidth={200}>File</Column>
                  <Column key="type" width="1.2fr" minWidth={150}>Type</Column>
                  <Column key="no" width={64} align="end">No.</Column>
                  <Column key="date" width={108}>Issued</Column>
                  <Column key="status" width={176}>Status</Column>
                  <Column key="act" width={48} hideHeader>Actions</Column>
                </TableHeader>
                <TableBody items={rows}>
                  {(d) => (
                    <Row key={d.id}>
                      <Cell textValue={d.name}>
                        <div className="filecell">
                          <FileBadge format={d.format} />
                          <div style={{ minWidth: 0 }}>
                            <div className="name" title={d.name}>{d.name}</div>
                            <div className="meta">{FORMAT_LABEL[d.format]} · {sizeLabel(d.size)}{d.phase !== 'uploading' ? ` · ${d.pages} ${d.pages === 1 ? 'page' : 'pages'}` : ''}</div>
                          </div>
                        </div>
                      </Cell>
                      <Cell textValue={typeInfo(d.type).label}>
                        {['uploading', 'reading', 'classifying'].includes(d.phase) || d.phase === 'failed' ? <span className="muted">-</span> : (
                          <div>
                            <div>{typeInfo(d.type).label}{typeInfo(d.type).internal && <Badge variant="purple" UNSAFE_style={{ marginLeft: 8, transform: 'scale(.85)', transformOrigin: 'left' }}>Internal</Badge>}</div>
                            <Confidence doc={d} />
                          </div>
                        )}
                      </Cell>
                      <Cell>{d.number ?? <span className="muted">-</span>}</Cell>
                      <Cell>{d.date ?? <span className="muted">-</span>}</Cell>
                      <Cell><Status doc={d} /></Cell>
                      <Cell>
                        <ActionMenu aria-label={`Actions for ${d.name}`} isQuiet onAction={(k) => {
                          if (k === 'open') setOpen(d.id);
                          if (k === 'confirm') confirm([d.id]);
                          if (k === 'retry') retry(d.id);
                          if (k === 'remove') setRemoving([d.id]);
                        }} disabledKeys={d.phase === 'review' ? [] : ['confirm']}>
                          {[
                            <Item key="open">Open details</Item>,
                            ...(d.phase === 'failed' ? [<Item key="retry">Try again</Item>] : [<Item key="confirm">Confirm</Item>]),
                            <Item key="remove">Remove from bid</Item>,
                          ]}
                        </ActionMenu>
                      </Cell>
                    </Row>
                  )}
                </TableBody>
              </TableView>
              <ActionBar
                isEmphasized
                selectedItemCount={selected === 'all' ? 'all' : selected.size}
                onClearSelection={() => setSelected(new Set())}
                onAction={(k) => {
                  if (k === 'confirm') { confirm(confirmable); ToastQueue.positive(`${confirmable.length} confirmed`, { timeout: 3000 }); setSelected(new Set()); }
                  if (k === 'remove') setRemoving(ids);
                }}
                disabledKeys={confirmable.length ? [] : ['confirm']}
              >
                <Item key="confirm">Confirm</Item>
                <Item key="remove">Remove</Item>
              </ActionBar>
            </ActionBarContainer>
            {current && <Inspector doc={current} onClose={() => setOpen(null)} onRemove={() => setRemoving([current.id])} />}
          </div>
          <p className="muted small" style={{ marginBottom: 0 }}>Documents are read in the order they were issued, not the order you add them. Issue dates decide which document wins.</p>
        </section>
      )}

      <DialogContainer onDismiss={() => setRemoving(null)}>
        {removing && (
          <AlertDialog title={removing.length === 1 ? 'Remove this document?' : `Remove ${removing.length} documents?`} variant="destructive"
            primaryActionLabel="Remove" cancelLabel="Keep"
            onPrimaryAction={() => { remove(removing); if (open && removing.includes(open)) setOpen(null); setSelected(new Set()); ToastQueue.neutral('Removed from the bid', { timeout: 3000 }); }}>
            {removing.length === 1 ? docs.find((d) => d.id === removing[0])?.name : `${removing.length} documents`} will be taken out of the bid. Its facts will not be read.
          </AlertDialog>
        )}
      </DialogContainer>
    </>
  );
}

function Inspector({ doc, onClose, onRemove }: { doc: Doc; onClose: () => void; onRemove: () => void }) {
  const { s, patch, setType, confirm, retry } = useIntake();
  const t = typeInfo(doc.type);
  const busy = ['uploading', 'reading', 'classifying', 'speakers'].includes(doc.phase);
  const locked = doc.confirmed;
  const gaps = missing(doc).filter((m) => m !== 'Speakers');
  const bases = s.docs.filter((d) => d.id !== doc.id && (d.type === 'rfp' || d.type === 'reissued-rfp'));
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape' && !document.querySelector('[role="dialog"], [role="listbox"]')) onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  return (
    <aside className="inspector" aria-label={`Details of ${doc.name}`}>
      <Flex alignItems="start" gap="size-100" marginBottom="size-150">
        <FileBadge format={doc.format} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <h3>{doc.name}</h3>
          <div className="muted small">d{doc.no} · {FORMAT_LABEL[doc.format]} · {sizeLabel(doc.size)}</div>
        </div>
        <ActionButton isQuiet aria-label="Close details" onPress={onClose}><Close /></ActionButton>
      </Flex>

      {doc.phase === 'failed' ? (
        <InlineAlert variant="negative">
          <Heading>Could not read this file</Heading>
          <Content>
            {doc.error}
            <Flex gap="size-100" marginTop="size-150">
              <Button variant="primary" onPress={() => retry(doc.id)}>Try again</Button>
              <Button variant="negative" style="outline" onPress={onRemove}>Remove</Button>
            </Flex>
          </Content>
        </InlineAlert>
      ) : busy ? (
        <Flex direction="column" gap="size-150" alignItems="center" UNSAFE_style={{ padding: '32px 0' }}>
          <ProgressCircle isIndeterminate aria-label="Working" />
          <span className="muted">{WORKING[doc.phase] ?? 'Uploading'}...</span>
        </Flex>
      ) : (
        <Flex direction="column" gap="size-200">
          <div>
            <div className="small muted" style={{ marginBottom: 4 }}>Why the model says so</div>
            <div className="evidence">{doc.proposal.evidence}</div>
          </div>
          <Picker label="Document type" items={DOC_TYPES} selectedKey={doc.type} isDisabled={locked} onSelectionChange={(k) => k && setType(doc.id, k as typeof doc.type)}
            description={t.description} width="100%">
            {(x) => <Item key={x.key}>{x.label}</Item>}
          </Picker>
          {doc.type === 'reissued-rfp' && (
            <Picker label="Replaces" isRequired items={bases} selectedKey={doc.replaces} isDisabled={locked} placeholder="Choose the earlier issue"
              onSelectionChange={(k) => patch(doc.id, { replaces: k ? String(k) : null })} width="100%">
              {(x) => <Item key={x.id}>{x.name}</Item>}
            </Picker>
          )}
          <Flex gap="size-150">
            {t.role === 'change' && (
              <NumberField label="Issue number" isRequired minValue={1} value={doc.number ?? NaN} isDisabled={locked}
                onChange={(n) => patch(doc.id, { number: Number.isNaN(n) ? null : n })} width="size-1600" />
            )}
            <DatePicker label="Issue date" isRequired={t.role !== 'base'} value={doc.date ? parseDate(doc.date) : null} isDisabled={locked}
              onChange={(v) => patch(doc.id, { date: v ? v.toString() : null })}
              validationState={t.role !== 'base' && !doc.date ? 'invalid' : undefined}
              errorMessage="An addendum, a call or notes need the date they were issued" />
          </Flex>
          <Flex gap="size-300">
            <LabeledValue label="Counts as" value={t.level} />
            <LabeledValue label="Shared outside" value={t.internal ? 'No, internal' : 'Yes'} />
          </Flex>
          {t.spoken && (
            <Well role="region" aria-label="Speakers">
              {doc.speakers.length
                ? `${doc.speakers.length} speakers found. You place each one on a side in the next step.`
                : 'No speakers could be found without the model. The call will be read with no speakers.'}
            </Well>
          )}
          <div>
            <div className="small muted" style={{ marginBottom: 4 }}>First lines</div>
            <div className="preview">{doc.preview.join('\n')}</div>
          </div>
          <Flex gap="size-100" justifyContent="end">
            <ActionButton isQuiet onPress={onRemove}><Delete /><Text>Remove</Text></ActionButton>
            <div style={{ flex: 1 }} />
            {locked ? (
              <Button variant="secondary" onPress={() => patch(doc.id, { confirmed: false, phase: 'review' })}>Edit</Button>
            ) : (
              <Button variant="accent" isDisabled={gaps.length > 0} onPress={() => confirm([doc.id])}>Confirm</Button>
            )}
          </Flex>
          {gaps.length > 0 && !locked && <span className="small muted" style={{ textAlign: 'right' }}>Add the {gaps.join(' and ').toLowerCase()} to confirm.</span>}
        </Flex>
      )}
    </aside>
  );
}
