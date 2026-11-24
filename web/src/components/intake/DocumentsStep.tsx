import { useMemo, useState } from 'react';
import {
  ActionBar, ActionBarContainer, ActionGroup, ActionMenu, AlertDialog, Button, Cell, Column, Content, DialogContainer, DropZone, FileTrigger, Flex,
  Heading, IllustratedMessage, InlineAlert, Item, ProgressCircle, Row, TableBody, TableHeader, TableView, Text, ToastQueue,
} from '@adobe/react-spectrum';
import MagicWand from '@spectrum-icons/workflow/MagicWand';
import UploadToCloud from '@spectrum-icons/workflow/UploadToCloud';
import type { BidFlow, UploadItem } from '../../bidFlow';
import {
  ACCEPTED, canAccept, docLight, FORMAT_LABEL, formatOf, inFilter, isAccepted, isEditable, isExtracted, isProblem, playbookOf, suggestedBy,
  type DocFilter,
} from '../../intake';
import { fileSizeLabel, playbookLabel } from '../../bid';
import type { Bid, BidDocument, BidDocumentPatch, Status } from '../../types';
import { Inspector } from './Inspector';
import { FileBadge, LightView } from './parts';
import './intake.css';

type RowItem = { id: string; kind: 'doc'; doc: BidDocument } | { id: string; kind: 'upload'; up: UploadItem };

/** The change that confirms a document as it stands; an issue number only means something for an addendum. */
export function confirmBody(doc: BidDocument, bid: Bid): BidDocumentPatch {
  const isChange = playbookOf(bid, doc)?.role === 'change';
  return { confirmed: true, issue_number: isChange ? doc.issue_number : null };
}

/** Step 2: add the files, check what each one is, confirm. One upload request reads the file, works out its type and finds its speakers. */
export function DocumentsStep({ flow, status }: { flow: BidFlow; status: Status | null }) {
  const bid = flow.bid;
  const [selected, setSelected] = useState<Set<string> | 'all'>(new Set());
  const [open, setOpen] = useState<number | null>(null);
  const [filter, setFilter] = useState<DocFilter>('all');
  const [refused, setRefused] = useState<string[]>([]);
  const [removing, setRemoving] = useState<number[] | null>(null);
  const hasKey = !!status?.has_key;

  const docs = useMemo(() => (bid ? [...bid.documents].sort((a, b) => a.no - b.no) : []), [bid]);
  const pbOf = (d: BidDocument) => (bid ? playbookOf(bid, d) : undefined);
  const uploads = flow.uploads;
  const failedUploads = uploads.filter((u) => u.status === 'error').length;
  const counts = {
    all: docs.length + uploads.length,
    review: docs.filter((d) => inFilter('review', d, pbOf(d))).length,
    confirmed: docs.filter((d) => d.confirmed).length,
    problems: docs.filter((d) => isProblem(d, pbOf(d))).length + failedUploads,
  };
  const rows = useMemo<RowItem[]>(() => [
    ...docs.filter((d) => inFilter(filter, d, pbOf(d))).map((doc): RowItem => ({ id: `d${doc.no}`, kind: 'doc', doc })),
    ...uploads.filter((u) => filter === 'all' || (filter === 'problems' && u.status === 'error')).map((up): RowItem => ({ id: `u${up.key}`, kind: 'upload', up })),
  ], [docs, uploads, filter, bid]);
  const ids = selected === 'all' ? rows.filter((r) => r.kind === 'doc').map((r) => r.id) : [...selected];
  const selectedDocs = ids.map((id) => docs.find((d) => `d${d.no}` === id)).filter((d): d is BidDocument => !!d);
  const confirmable = selectedDocs.filter((d) => canAccept(d, pbOf(d)));
  // "Accept N suggestions" is offered for what the model suggested; rules only guess, so each of those is checked by hand.
  const acceptAll = docs.filter((d) => canAccept(d, pbOf(d)) && d.proposed.by === 'model');
  const current = docs.find((d) => d.no === open) ?? null;

  const take = (files: File[]) => {
    setRefused(files.filter((f) => !isAccepted(f.name)).map((f) => f.name));
    const ok = files.filter((f) => isAccepted(f.name));
    if (ok.length) flow.addFiles(ok);
  };
  const confirm = async (list: BidDocument[]) => {
    if (!bid) return;
    const n = await flow.patchMany(list.map((d) => ({ no: d.no, body: confirmBody(d, bid) })));
    if (n) ToastQueue.positive(n === 1 ? '1 document confirmed' : `${n} documents confirmed`, { timeout: 3000 });
    setSelected(new Set());
  };
  const remove = async (nos: number[]) => {
    const n = await flow.removeMany(nos);
    if (n) ToastQueue.neutral(n === 1 ? 'Removed from the bid' : `${n} documents removed from the bid`, { timeout: 3000 });
    if (open !== null && nos.includes(open)) setOpen(null);
    setSelected(new Set());
  };

  const browse = (label: string, variant: 'accent' | 'secondary') => (
    <FileTrigger allowsMultiple acceptedFileTypes={ACCEPTED} onSelect={(l) => take(Array.from(l ?? []))}>
      <Button variant={variant} style={variant === 'secondary' ? 'outline' : undefined}>{label}</Button>
    </FileTrigger>
  );
  const empty = docs.length === 0 && uploads.length === 0;
  const drop = (
    <DropZone
      isFilled={!empty}
      replaceMessage="Drop to add these documents"
      onDrop={async (e) => {
        const files = await Promise.all(e.items.map(async (i) => (i.kind === 'file' ? await i.getFile() : null)));
        take(files.filter((f): f is File => !!f));
      }}
      UNSAFE_style={{ width: '100%', boxSizing: 'border-box', minHeight: empty ? 220 : 0, padding: empty ? undefined : '4px 16px' }}
    >
      {empty ? (
        <IllustratedMessage>
          <UploadToCloud size="XXL" />
          <Heading>Drop the bid documents here</Heading>
          <Content>
            <Flex direction="column" alignItems="center" gap="size-150">
              <span>RFP, addenda, forms, call transcripts and deal notes. PDF, Word, Excel, CSV, JSON or text.</span>
              {browse('Browse files', 'accent')}
            </Flex>
          </Content>
        </IllustratedMessage>
      ) : (
        <Flex alignItems="center" gap="size-150" UNSAFE_style={{ padding: 12 }}>
          <UploadToCloud />
          <Text>Drop more files here, or</Text>
          {browse('Browse', 'secondary')}
        </Flex>
      )}
    </DropZone>
  );

  return (
    <>
      <section className="in-card" aria-labelledby="docs-h">
        <Flex alignItems="start" gap="size-200" wrap>
          <div className="in-grow">
            <h2 id="docs-h">Documents</h2>
            <p className="in-lede">Add everything that belongs to this bid. Each file is read and its type is suggested; you confirm or correct it.</p>
          </div>
          {acceptAll.length > 1 && (
            <Button variant="primary" style="outline" onPress={() => void confirm(acceptAll)}>
              <MagicWand />
              <Text>Accept {acceptAll.length} suggestions</Text>
            </Button>
          )}
        </Flex>
        {status && !hasKey && (
          <InlineAlert variant="notice" marginBottom="size-200">
            <Heading>No API key</Heading>
            <Content>Without it, types are only guessed by simple rules and the speakers of a call cannot be found. Check every type before confirming.</Content>
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

      {!empty && (
        <section className="in-card" aria-label="Uploaded documents">
          <Flex alignItems="center" marginBottom="size-150" gap="size-200" wrap>
            <ActionGroup selectionMode="single" disallowEmptySelection selectedKeys={[filter]} onSelectionChange={(k) => setFilter([...k][0] as DocFilter)} density="compact" aria-label="Show">
              <Item key="all">{`All ${counts.all}`}</Item>
              <Item key="review">{`To review ${counts.review}`}</Item>
              <Item key="confirmed">{`Confirmed ${counts.confirmed}`}</Item>
              <Item key="problems">{`Problems ${counts.problems}`}</Item>
            </ActionGroup>
            <div className="in-grow" />
            <span className="in-muted in-small">Select a row to open its details.</span>
          </Flex>
          <ActionBarContainer height={Math.min(660, 72 + Math.max(rows.length, 2) * 80)}>
            <TableView
              aria-label="Documents of this bid"
              selectionMode="multiple"
              selectedKeys={selected}
              disabledKeys={rows.filter((r) => r.kind === 'upload').map((r) => r.id)}
              disabledBehavior="selection"
              onSelectionChange={(k) => setSelected(k === 'all' ? 'all' : new Set([...k].map(String)))}
              onAction={(k) => {
                const id = String(k);
                if (id.startsWith('d')) setOpen(Number(id.slice(1)));
              }}
              overflowMode="wrap"
              density="spacious"
              renderEmptyState={() => <div className="in-muted">Nothing here.</div>}
            >
              <TableHeader>
                <Column key="file" width="2fr" minWidth={200}>File</Column>
                <Column key="type" width="1.2fr" minWidth={150}>Type</Column>
                <Column key="no" width={64} align="end">No.</Column>
                <Column key="date" width={108}>Issued</Column>
                <Column key="status" width={180}>Status</Column>
                <Column key="act" width={48} hideHeader>Actions</Column>
              </TableHeader>
              <TableBody items={rows}>
                {(r) => r.kind === 'upload' ? uploadRow(r.up, flow) : (
                  <Row key={r.id}>
                    <Cell textValue={r.doc.file_name}>
                      <div className="in-filecell">
                        <FileBadge name={r.doc.file_name} />
                        <div style={{ minWidth: 0 }}>
                          <div className="in-name" title={r.doc.file_name}>{r.doc.file_name}</div>
                          <div className="in-meta">d{r.doc.no} · {FORMAT_LABEL[formatOf(r.doc.file_name)]}{r.doc.pages ? ` · ${r.doc.pages} ${r.doc.pages === 1 ? 'page' : 'pages'}` : ''}</div>
                        </div>
                      </div>
                    </Cell>
                    <Cell textValue={playbookLabel(r.doc.playbook)}>
                      <div>
                        <div>{playbookLabel(r.doc.playbook)}{pbOf(r.doc)?.visibility === 'internal' && <span className="in-muted"> · internal</span>}</div>
                        {isEditable(r.doc) && <span className="in-suggest"><MagicWand size="XS" /> {suggestedBy(r.doc)}</span>}
                      </div>
                    </Cell>
                    <Cell>{pbOf(r.doc)?.role === 'change' && r.doc.issue_number ? r.doc.issue_number : <span className="in-muted">-</span>}</Cell>
                    <Cell>{r.doc.issue_date ?? <span className="in-muted">-</span>}</Cell>
                    <Cell><LightView light={docLight(r.doc, pbOf(r.doc))} /></Cell>
                    <Cell>
                      <DocMenu doc={r.doc} bid={bid as Bid} onOpen={() => setOpen(r.doc.no)} onConfirm={() => void confirm([r.doc])}
                        onEdit={() => void flow.patchDocument(r.doc.no, { confirmed: false })} onRemove={() => setRemoving([r.doc.no])} />
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
                if (k === 'confirm') void confirm(confirmable);
                if (k === 'remove') setRemoving(selectedDocs.filter((d) => !isExtracted(d) && d.status !== 'extracting').map((d) => d.no));
              }}
              disabledKeys={confirmable.length ? [] : ['confirm']}
            >
              <Item key="confirm">Confirm</Item>
              <Item key="remove">Remove</Item>
            </ActionBar>
          </ActionBarContainer>
          <p className="in-muted in-small" style={{ marginBottom: 0 }}>Documents are read in the order they were issued, not the order you add them. Issue order decides which document wins.</p>
        </section>
      )}

      {current && bid && (
        <Inspector
          key={current.no}
          doc={current}
          bid={bid}
          hasKey={hasKey}
          onClose={() => setOpen(null)}
          onPatch={(body) => flow.patchDocument(current.no, body)}
          onConfirm={() => void confirm([current])}
          onRemove={() => setRemoving([current.no])}
        />
      )}

      <DialogContainer onDismiss={() => setRemoving(null)}>
        {removing && removing.length > 0 && (
          <AlertDialog
            title={removing.length === 1 ? 'Remove this document?' : `Remove ${removing.length} documents?`}
            variant="destructive"
            primaryActionLabel="Remove"
            cancelLabel="Keep"
            onPrimaryAction={() => void remove(removing)}
          >
            {removing.length === 1 ? docs.find((d) => d.no === removing[0])?.file_name : `${removing.length} documents`} will be taken out of the bid. This cannot be undone.
          </AlertDialog>
        )}
      </DialogContainer>
    </>
  );
}

/** The row of a file on its way up, or one the server refused. A plain function: a table body takes its `Row` directly. */
function uploadRow(up: UploadItem, flow: BidFlow) {
  return (
    <Row key={`u${up.key}`}>
      <Cell textValue={up.name}>
        <div className="in-filecell">
          <FileBadge name={up.name} />
          <div style={{ minWidth: 0 }}>
            <div className="in-name" title={up.name}>{up.name}</div>
            <div className="in-meta">{FORMAT_LABEL[formatOf(up.name)]} · {fileSizeLabel(up.size)}</div>
            {up.status === 'error' && <div role="alert" className="in-bad in-small">{up.error}</div>}
          </div>
        </div>
      </Cell>
      <Cell><span className="in-muted">-</span></Cell>
      <Cell><span className="in-muted">-</span></Cell>
      <Cell><span className="in-muted">-</span></Cell>
      <Cell>
        {up.status === 'pending' ? (
          <Flex alignItems="center" gap="size-100" UNSAFE_className="in-small">
            <ProgressCircle size="S" isIndeterminate aria-label={`Uploading and reading ${up.name}`} />
            <span role="status">Uploading and reading</span>
          </Flex>
        ) : (
          <LightView light={{ tone: 'negative', text: 'Could not read' }} />
        )}
      </Cell>
      <Cell>
        {up.status === 'error' ? (
          <ActionMenu aria-label={`Actions for ${up.name}`} isQuiet onAction={(k) => (k === 'retry' ? flow.retryUpload(up.key) : flow.dismissUpload(up.key))}>
            <Item key="retry">Try again</Item>
            <Item key="dismiss">Dismiss</Item>
          </ActionMenu>
        ) : <span />}
      </Cell>
    </Row>
  );
}

/** The menu at the end of a document row. */
function DocMenu({ doc, bid, onOpen, onConfirm, onEdit, onRemove }: {
  doc: BidDocument; bid: Bid; onOpen: () => void; onConfirm: () => void; onEdit: () => void; onRemove: () => void;
}) {
  const locked = isExtracted(doc) || doc.status === 'extracting';
  const items = [
    <Item key="open">Open details</Item>,
    ...(doc.confirmed ? [<Item key="edit">Edit</Item>] : [<Item key="confirm">Confirm</Item>]),
    <Item key="remove">Remove from bid</Item>,
  ];
  const disabled = [
    ...(locked ? ['edit', 'remove'] : []),
    ...(!canAccept(doc, playbookOf(bid, doc)) ? ['confirm'] : []),
  ];
  return (
    <ActionMenu aria-label={`Actions for ${doc.file_name}`} isQuiet disabledKeys={disabled}
      onAction={(k) => ({ open: onOpen, confirm: onConfirm, edit: onEdit, remove: onRemove } as Record<string, () => void>)[String(k)]?.()}>
      {items}
    </ActionMenu>
  );
}
