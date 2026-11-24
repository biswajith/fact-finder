import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from 'react';
import { ActionButton, Button, Content, DatePicker, Flex, Heading, InlineAlert, Item, LabeledValue, NumberField, Picker, Text, Well } from '@adobe/react-spectrum';
import { parseDate } from '@internationalized/date';
import Close from '@spectrum-icons/workflow/Close';
import Delete from '@spectrum-icons/workflow/Delete';
import MagicWand from '@spectrum-icons/workflow/MagicWand';
import { levelLabel, missingWords, playbookLabel } from '../../bid';
import { FORMAT_LABEL, formatOf, gapsOf, isEditable, isExtracted, playbookOf, sharedLabel, suggestedBy } from '../../intake';
import type { Bid, BidDocument, BidDocumentPatch } from '../../types';
import { FileBadge } from './parts';
import './intake.css';

/** Where the panel sits: over the right edge of the column the page scrolls in, above the bar at the foot of the step. */
function usePanelBox(): CSSProperties {
  const [box, setBox] = useState<CSSProperties>({});
  useLayoutEffect(() => {
    const measure = () => {
      const col = document.querySelector('.main-scroll')?.getBoundingClientRect();
      const foot = document.querySelector('.in-footer')?.getBoundingClientRect();
      const footH = foot && foot.top < window.innerHeight ? window.innerHeight - foot.top : 0;
      setBox({
        top: col ? col.top : 0,
        right: col ? Math.max(0, window.innerWidth - col.right) : 0,
        bottom: Math.max(footH, col ? Math.max(0, window.innerHeight - col.bottom) : 0),
      });
    };
    measure();
    window.addEventListener('resize', measure);
    window.addEventListener('scroll', measure, true);
    return () => {
      window.removeEventListener('resize', measure);
      window.removeEventListener('scroll', measure, true);
    };
  }, []);
  return box;
}

/** The detail panel of one document: what it is, the numbers it needs, and confirm, edit or remove. Slides over from the right; Escape or × closes it. */
export function Inspector({ doc, bid, hasKey, onClose, onPatch, onConfirm, onRemove }: {
  doc: BidDocument;
  bid: Bid;
  hasKey: boolean;
  onClose: () => void;
  onPatch: (body: BidDocumentPatch) => Promise<boolean>;
  onConfirm: () => void;
  onRemove: () => void;
}) {
  const box = usePanelBox();
  const panel = useRef<HTMLElement>(null);
  const pb = playbookOf(bid, doc);
  const editable = isEditable(doc);
  const locked = !editable;
  const extracted = isExtracted(doc);
  const gaps = gapsOf(doc, pb);
  const bases = bid.documents.filter((d) => d.no !== doc.no && (d.playbook === 'rfp' || d.playbook === 'reissued-rfp'));
  // The fields start from the document and are sent as soon as they are set, so the panel never waits on the server to type.
  const [date, setDate] = useState(doc.issue_date);
  const [number, setNumber] = useState<number | null>(doc.issue_number);
  useEffect(() => setDate(doc.issue_date), [doc.issue_date]);
  useEffect(() => setNumber(doc.issue_number), [doc.issue_number]);
  useEffect(() => {
    panel.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !document.querySelector('[role="dialog"], [role="alertdialog"], [role="listbox"]')) onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <aside className="in-inspector" style={box} ref={panel} tabIndex={-1} aria-label={`Details of ${doc.file_name}`}>
      <Flex alignItems="start" gap="size-100" marginBottom="size-150">
        <FileBadge name={doc.file_name} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <h3>{doc.file_name}</h3>
          <div className="in-muted in-small">
            d{doc.no} · {FORMAT_LABEL[formatOf(doc.file_name)]}{doc.pages ? ` · ${doc.pages} ${doc.pages === 1 ? 'page' : 'pages'}` : ''}
          </div>
        </div>
        <ActionButton isQuiet aria-label="Close details" onPress={onClose}><Close /></ActionButton>
      </Flex>

      {doc.status === 'failed' && (
        <InlineAlert variant="negative" marginBottom="size-200">
          <Heading>Could not read this file</Heading>
          <Content>
            <div className="in-text">{doc.error || 'The last extraction of this document failed.'}</div>
            <div className="in-muted in-small" style={{ marginTop: 6 }}>Starting the extraction again from the review step tries it once more.</div>
          </Content>
        </InlineAlert>
      )}

      <Flex direction="column" gap="size-200">
        {editable && (
          <div>
            <span className="in-suggest"><MagicWand size="XS" /> {suggestedBy(doc)}</span>
            {doc.proposed.checked === false && (
              <div className="in-warn" style={{ marginTop: 6 }}>The suggested number or date was not found in the document; check it.</div>
            )}
          </div>
        )}
        <Picker
          label="Document type"
          items={bid.playbooks}
          selectedKey={pb ? pb.name : null}
          isDisabled={locked}
          onSelectionChange={(k) => k !== null && String(k) !== doc.playbook && void onPatch({ playbook: String(k) })}
          description={pb?.description}
          width="100%"
        >
          {(p) => <Item key={p.name}>{playbookLabel(p.name)}</Item>}
        </Picker>
        {doc.playbook === 'reissued-rfp' && (
          <Picker
            label="Replaces"
            isRequired
            items={bases}
            selectedKey={doc.previous}
            isDisabled={locked}
            placeholder="Choose the earlier issue"
            onSelectionChange={(k) => k !== null && void onPatch({ previous: String(k) })}
            width="100%"
          >
            {(d) => <Item key={d.doc_id}>{`d${d.no} ${d.file_name}`}</Item>}
          </Picker>
        )}
        <Flex gap="size-150" wrap>
          {pb?.role === 'change' && (
            <NumberField
              label="Issue number"
              isRequired
              minValue={1}
              step={1}
              value={number ?? NaN}
              isDisabled={locked}
              onChange={(n) => {
                const v = Number.isNaN(n) ? null : n;
                setNumber(v);
                if (v !== doc.issue_number) void onPatch({ issue_number: v });
              }}
              width="size-1600"
            />
          )}
          <DatePicker
            label="Issue date"
            isRequired={!!pb && pb.role !== 'base'}
            value={date ? parseDate(date) : null}
            isDisabled={locked}
            onChange={(v) => {
              const iso = v ? v.toString() : null;
              setDate(iso);
              if (iso !== doc.issue_date) void onPatch({ issue_date: iso });
            }}
            validationState={pb && pb.role !== 'base' && !date ? 'invalid' : undefined}
            errorMessage="An addendum, a call or notes need the date they were issued"
          />
        </Flex>
        {pb && (
          <Flex gap="size-300" wrap>
            <LabeledValue label="Counts as" value={levelLabel(pb)} />
            <LabeledValue label="Shared outside" value={sharedLabel(pb)} />
          </Flex>
        )}
        {pb?.spoken && !extracted && (
          <Well role="region" aria-label="Speakers">
            {doc.speakers.length
              ? `${doc.speakers.length} ${doc.speakers.length === 1 ? 'speaker' : 'speakers'} found. You place each one on a side in the next step.`
              : doc.missing.includes('speakers not read yet')
                ? hasKey
                  ? 'The speakers of this call have not been read yet. You can ask for them in the next step.'
                  : 'The speakers of this call cannot be read without an API key.'
                : 'No speakers were found in this call.'}
          </Well>
        )}
        {doc.confirmed && !extracted && missingWords(doc.missing) && <div className="in-muted in-small">{missingWords(doc.missing)}</div>}
        <Flex gap="size-100" justifyContent="end" alignItems="center">
          <ActionButton isQuiet isDisabled={extracted || doc.status === 'extracting'} onPress={onRemove}><Delete /><Text>Remove</Text></ActionButton>
          <div style={{ flex: 1 }} />
          {doc.confirmed && !extracted ? (
            <Button variant="secondary" isDisabled={doc.status === 'extracting'} onPress={() => void onPatch({ confirmed: false })}>Edit</Button>
          ) : editable ? (
            <Button variant="accent" isDisabled={!pb || gaps.length > 0} onPress={onConfirm}>Confirm</Button>
          ) : null}
        </Flex>
        {gaps.length > 0 && editable && <span className="in-muted in-small" style={{ textAlign: 'right' }}>Add the {gaps.join(' and ')} to confirm.</span>}
      </Flex>
    </aside>
  );
}
