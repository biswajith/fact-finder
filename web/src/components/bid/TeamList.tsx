import { useState } from 'react';
import { Button, TextArea } from '@adobe/react-spectrum';

const linesOf = (text: string) => text.split('\n').map((l) => l.trim()).filter(Boolean);

export function TeamList({ team, onSave, open }: { team: { name: string }[]; onSave: (names: string[]) => Promise<boolean>; open?: boolean }) {
  const saved = team.map((t) => t.name).join('\n');
  const [text, setText] = useState(saved);
  const [busy, setBusy] = useState(false);
  const changed = linesOf(text).join('\n') !== saved;
  return (
    <details className="pg-fold" open={open}>
      <summary>Our team</summary>
      <div className="pg-stack">
      <TextArea label="Team members, one name per line" value={text} onChange={setText} width="100%" />
      <div className="muted">Names are matched exactly to speakers. Saving suggests sides again for calls not yet confirmed.</div>
      <div>
        <Button
          variant="secondary"
          isDisabled={!changed || busy}
          onPress={async () => {
            setBusy(true);
            await onSave(linesOf(text));
            setBusy(false);
          }}
        >
          Save team
        </Button>
      </div>
      </div>
    </details>
  );
}
