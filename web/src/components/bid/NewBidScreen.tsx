import { useState, type FormEvent } from 'react';
import { Button, TextField } from '@adobe/react-spectrum';
import { fileSizeLabel } from '../../bid';
import type { BidFlow } from '../../bidFlow';
import { PageHeader } from '../shell/PageHeader';
import '../pages.css';
import { DropZone } from './DropZone';

/** The one place a bid is made: a name, and optionally its first documents, which go up once the bid exists. */
export function NewBidScreen({ flow }: { flow: BidFlow }) {
  const [name, setName] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const canCancel = (flow.bids?.length ?? 0) > 0;

  const choose = (more: File[]) => setFiles((cur) => [...cur, ...more.filter((f, i) => !cur.some((c) => c.name === f.name) && more.findIndex((x) => x.name === f.name) === i)]);
  const create = async (e?: FormEvent) => {
    e?.preventDefault();
    if (!name.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      await flow.createBid(name, files);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  };
  const label = files.length ? `Create bid and add ${files.length} ${files.length === 1 ? 'document' : 'documents'}` : 'Create bid';

  return (
    <form className="pg-newbid" onSubmit={(e) => void create(e)} aria-label="New bid">
      <PageHeader
        title="New bid"
        subtitle="A bid holds the RFP and everything that comes with it: addenda, templates, call transcripts and deal notes. They are read together into one fact list."
      />
      <TextField label="Bid name" autoFocus isRequired width="100%" placeholder="Customer and project" value={name} onChange={setName} />
      <div>
        <DropZone onFiles={choose} title="Documents (optional, you can add more later)" />
        {files.length > 0 && (
          <ul className="pg-newbid-files" aria-label="Documents to add">
            {files.map((f) => (
              <li key={f.name}>
                <span className="grow wrap-text">{f.name} <span className="muted">· {fileSizeLabel(f.size)}</span></span>
                <Button variant="secondary" isQuiet aria-label={`Remove ${f.name}`} isDisabled={busy} onPress={() => setFiles((cur) => cur.filter((x) => x.name !== f.name))}>Remove</Button>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="pg-newbid-actions">
        {canCancel && <Button variant="secondary" isDisabled={busy} onPress={flow.cancelNew}>Cancel</Button>}
        <Button type="submit" variant="accent" isDisabled={!name.trim() || busy}>{busy ? 'Creating...' : label}</Button>
      </div>
      {error && <div role="alert" className="pg-bad wrap-text">{error}</div>}
    </form>
  );
}
