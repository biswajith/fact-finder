import { useState } from 'react';
import { Button, ButtonGroup, Content, Dialog, DialogTrigger, Divider, FileTrigger, Heading, Item, Picker, ToastQueue } from '@adobe/react-spectrum';
import * as api from '../api';
import { useAsync } from '../hooks';
import { errorText, useRun } from '../store';
import { ErrorBox } from './common';

function PdfDialog({ close }: { close: () => void }) {
  const { run, runInfo, refreshRuns } = useRun();
  const hasPdf = !!runInfo?.has_pdf;
  const pdfs = useAsync((signal) => api.getPdfs(signal), [], !hasPdf);
  const [path, setPath] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const done = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true);
    try {
      await fn();
      const runs = await refreshRuns();
      ToastQueue.positive(ok, { timeout: 3000 });
      if (runs.find((r) => r.run === run)?.has_pdf === hasPdf && hasPdf) ToastQueue.info("This run's own source.pdf stays.", { timeout: 5000 });
      close();
    } catch (e) {
      ToastQueue.negative(errorText(e), { timeout: 8000 });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog aria-label="PDF for this run">
      <Heading>PDF for this run</Heading>
      <Divider />
      <Content>
        {hasPdf ? (
          <p>{runInfo?.pdf_name ? `Showing pages from ${runInfo.pdf_name}.` : 'This run has a PDF.'}</p>
        ) : (
          <div className="form-col">
            <p>This run has no PDF, so fact pages show the cited text only. Pick one from the working directory or upload one.</p>
            {pdfs.error ? (
              <ErrorBox message={pdfs.error} onRetry={pdfs.reload} />
            ) : (
              <Picker
                label="PDF in the working directory"
                placeholder={pdfs.loading ? 'Loading...' : pdfs.data?.length === 0 ? '(none found)' : '(choose)'}
                items={pdfs.data ?? []}
                selectedKey={path}
                onSelectionChange={(k) => setPath(k === null ? null : String(k))}
                isDisabled={busy || !pdfs.data?.length}
              >
                {(p) => <Item key={p.path}>{p.path}</Item>}
              </Picker>
            )}
          </div>
        )}
      </Content>
      <ButtonGroup>
        <Button variant="secondary" onPress={close}>Close</Button>
        {hasPdf ? (
          <Button variant="negative" isDisabled={busy} onPress={() => void done(() => api.detachPdf(run), 'PDF removed from this run')}>Remove PDF</Button>
        ) : (
          <>
            <FileTrigger acceptedFileTypes={['application/pdf']} onSelect={(files) => { const f = files?.[0]; if (f) void done(() => api.attachPdfUpload(run, f), 'PDF attached'); }}>
              <Button variant="secondary" isDisabled={busy}>Upload a PDF</Button>
            </FileTrigger>
            <Button variant="accent" isDisabled={busy || !path} onPress={() => void done(() => api.attachPdfPath(run, path as string), 'PDF attached')}>Use this PDF</Button>
          </>
        )}
      </ButtonGroup>
    </Dialog>
  );
}

/** Pages and PDF name beside the run, with a control to attach or remove the PDF. */
export function PdfControl() {
  const { runInfo, facts } = useRun();
  const pages = facts.data?.pages;
  const hasPdf = !!runInfo?.has_pdf;
  return (
    <span className="pdf-line">
      {pages ? <span className="muted">{pages} pages</span> : null}
      <span className="muted">{hasPdf ? (runInfo?.pdf_name || 'PDF attached') : 'No PDF'}</span>
      <DialogTrigger>
        <Button variant="secondary" aria-label={hasPdf ? 'Change or remove the PDF' : 'Attach a PDF to this run'}>{hasPdf ? 'PDF' : 'Attach PDF'}</Button>
        {(close) => <PdfDialog close={close} />}
      </DialogTrigger>
    </span>
  );
}
