import { useState } from 'react';
import { Button, ButtonGroup, CheckboxGroup, Checkbox, Item, Picker, TextArea, TextField } from '@adobe/react-spectrum';
import type { CategoryCode, Fact, Flag } from '../types';
import { CATEGORY_CODES, CATEGORY_NAMES, FLAGS } from '../types';

export interface FactFormValues {
  category: CategoryCode;
  text: string;
  flags: Flag[];
  note: string;
  reason: string;
  citationIds: string;
}

/** Form used both to edit a fact and to add a new one (`fact` undefined). */
export function FactForm({
  fact, busy, onSubmit, onCancel,
}: {
  fact?: Fact;
  busy: boolean;
  onSubmit: (v: FactFormValues) => void;
  onCancel: () => void;
}) {
  const [category, setCategory] = useState<CategoryCode>(fact?.category ?? 'R');
  // A bid's facts can carry a category or flags the form does not offer for a new fact; keep them choosable.
  const codes = CATEGORY_CODES.includes(category) ? CATEGORY_CODES : [...CATEGORY_CODES, category];
  const flagChoices = [...FLAGS, ...(fact?.flags ?? []).filter((x) => !FLAGS.includes(x))];
  const [text, setText] = useState(fact?.text ?? '');
  const [flags, setFlags] = useState<Flag[]>(fact?.flags ?? []);
  const [note, setNote] = useState(fact?.note ?? '');
  const [reason, setReason] = useState('');
  const [citationIds, setCitationIds] = useState('');
  return (
    <form
      className="fx-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (text.trim()) onSubmit({ category, text: text.trim(), flags, note, reason, citationIds });
      }}
    >
      <TextArea label="Text" value={text} onChange={setText} isRequired width="100%" />
      <Picker label="Category" selectedKey={category} onSelectionChange={(k) => setCategory(String(k) as CategoryCode)}>
        {codes.map((c) => (
          <Item key={c}>{`${c}: ${CATEGORY_NAMES[c]}`}</Item>
        ))}
      </Picker>
      <CheckboxGroup label="Flags" orientation="horizontal" value={flags} onChange={(v) => setFlags(v as Flag[])}>
        {flagChoices.map((f) => (
          <Checkbox key={f} value={f}>
            {f}
          </Checkbox>
        ))}
      </CheckboxGroup>
      <TextArea label="Note" value={note} onChange={setNote} width="100%" />
      {!fact && (
        <TextField
          label="Cited unit IDs (optional, separated by commas)"
          value={citationIds}
          onChange={setCitationIds}
          width="100%"
        />
      )}
      {fact && <TextField label="Why are you changing this? (optional)" value={reason} onChange={setReason} width="100%" />}
      <ButtonGroup>
        <Button type="submit" variant="accent" isDisabled={busy || !text.trim()}>
          {fact ? 'Save change' : 'Add fact'}
        </Button>
        <Button variant="secondary" onPress={onCancel}>
          Cancel
        </Button>
      </ButtonGroup>
    </form>
  );
}
