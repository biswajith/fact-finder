import { useRef, useState, type DragEvent, type KeyboardEvent } from 'react';
import { Button, FileTrigger } from '@adobe/react-spectrum';

export const ACCEPTED = ['.pdf', '.json', '.txt', '.md', '.csv', '.xlsx'];
const accepted = (name: string) => ACCEPTED.some((ext) => name.toLowerCase().endsWith(ext));

/** Drag files here or choose them; the files go up one at a time in the order given. */
const HINT = 'RFPs, addenda and templates (PDF, spreadsheet), call transcripts (Gong export or text) and deal notes.';

/** `title` is the section heading (null: none, the page gives one); `hint` the line under the zone. */
export function DropZone({ onFiles, title = 'Add documents', hint = HINT }: { onFiles: (files: File[]) => void; title?: string | null; hint?: string }) {
  const [over, setOver] = useState(false);
  const [refused, setRefused] = useState<string[]>([]);
  const input = useRef<HTMLInputElement>(null);

  const take = (list: FileList | File[] | null) => {
    const files = Array.from(list ?? []);
    setRefused(files.filter((f) => !accepted(f.name)).map((f) => f.name));
    const ok = files.filter((f) => accepted(f.name));
    if (ok.length) onFiles(ok);
  };
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    take(e.dataTransfer.files);
  };
  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      input.current?.click();
    }
  };

  return (
    <section className="pg-form" aria-labelledby={title ? 'drop-title' : undefined} aria-label={title ? undefined : 'Add documents'}>
      {title && <h2 className="pg-h2" id="drop-title">{title}</h2>}
      <div
        className={`pg-drop${over ? ' over' : ''}`}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={onDrop}
      >
        <div
          className="pg-drop-target"
          role="button"
          tabIndex={0}
          aria-label="Add documents: drop files here, or press Enter to choose files"
          onKeyDown={onKey}
          onClick={() => input.current?.click()}
        >
          Drop files here
        </div>
        <FileTrigger ref={input} allowsMultiple acceptedFileTypes={ACCEPTED} onSelect={take}>
          <Button variant="secondary">Choose files</Button>
        </FileTrigger>
      </div>
      <div className="muted">{hint}</div>
      {refused.length > 0 && (
        <div role="alert" className="pg-note wrap-text">Not added, this file type is not supported: {refused.join(', ')}</div>
      )}
    </section>
  );
}
