import {
  Button, Checkbox, FileTrigger, Item, Picker, ProgressCircle, Radio, RadioGroup, TextField,
} from '@adobe/react-spectrum';
import * as api from '../api';
import { VOTES, type NewRun } from '../newRun';
import type { Status } from '../types';
import { useAsync } from '../hooks';
import { Empty, ErrorBox } from './common';
import { PageHeader } from './shell/PageHeader';
import './pages.css';

export function NewRunTab({ n, status }: { n: NewRun; status: Status | null }) {
  const pdfs = useAsync((signal) => api.getPdfs(signal), [], n.mode === 'pick');
  const plan = n.planOf;
  const stored = plan?.stored ?? null;
  const done = n.job?.status === 'done' ? n.job : null;
  const failed = n.job?.status === 'failed' ? n.job : null;

  return (
    <>
    <PageHeader title="New run" subtitle="Extract the facts from an RFP PDF" />
    <div className="pg-stack pg-narrow">
      {done && (
        <div className="pg-banner ok" role="status">
          <strong>Run finished</strong>
          <div className="wrap-text">{done.result}</div>
          {done.run && <div className="muted">Written to {done.run}. It is now the open run.</div>}
        </div>
      )}
      {failed && (
        <div className="pg-banner bad" role="alert">
          <strong>The run failed and nothing was written</strong>
          <span className="wrap-text">{failed.error}</span>
        </div>
      )}
      <div className="pg-note">Runs are written to runs/&lt;doc_id&gt;/&lt;run_id&gt;/ with facts.json, report.json and source.pdf.</div>
      <div className="pg-form">
        <RadioGroup label="PDF" orientation="horizontal" value={n.mode} onChange={(v) => n.setMode(v as 'pick' | 'upload')}>
          <Radio value="pick">Pick from the working directory</Radio>
          <Radio value="upload">Upload</Radio>
        </RadioGroup>
        {n.mode === 'pick' ? (
          pdfs.error ? (
            <ErrorBox message={pdfs.error} onRetry={pdfs.reload} />
          ) : pdfs.data && pdfs.data.length === 0 ? (
            <Empty>No PDF files in the working directory. Upload one instead.</Empty>
          ) : (
            <Picker
              label="PDF file"
              placeholder={pdfs.loading ? 'Loading...' : '(choose)'}
              items={pdfs.data ?? []}
              selectedKey={n.picked?.path ?? null}
              onSelectionChange={(k) => {
                const p = (pdfs.data ?? []).find((x) => x.path === String(k));
                n.choosePick(p ?? null);
              }}
            >
              {(p) => <Item key={p.path}>{p.path}</Item>}
            </Picker>
          )
        ) : (
          <div className="row">
            <FileTrigger acceptedFileTypes={['application/pdf']} onSelect={(files) => { const f = files?.[0]; if (f) void n.chooseUpload(f); }}>
              <Button variant="secondary" isDisabled={n.uploading}>{n.uploading ? 'Uploading...' : 'Choose a PDF file'}</Button>
            </FileTrigger>
            {n.upload && <span>{n.upload.name} ({n.upload.pages} pages)</span>}
            {n.uploadError && <span role="alert" className="wrap-text">{n.uploadError}</span>}
          </div>
        )}
        <TextField label="Deal ID" value={n.dealId} onChange={n.setDealId} isRequired />
        <TextField label="Doc ID" value={n.docId} onChange={n.setDocEdit} isRequired />
        <TextField label="Model" value={n.modelValue} onChange={n.setModel} />
        <RadioGroup
          label="Votes per unit"
          orientation="horizontal"
          value={String(n.votes)}
          onChange={(v) => n.setVotes(Number(v))}
        >
          {VOTES.map((v) => <Radio key={v} value={String(v)}>{String(v)}</Radio>)}
        </RadioGroup>
        <div className="muted">Each unit of the RFP is labelled this many times and the majority wins.</div>
      </div>

      {n.hasSource && n.docId.trim() && (
        n.plan.error ? (
          <ErrorBox message={`Could not plan this PDF: ${n.plan.error}`} onRetry={n.plan.reload} />
        ) : n.plan.loading && !plan ? (
          <div className="row"><ProgressCircle aria-label="Planning the calls" isIndeterminate size="S" /> Reading the PDF...</div>
        ) : plan ? (
          <details className="pg-fold">
            <summary>Planned calls: {plan.total_calls} calls over {plan.units} units, sent together</summary>
            <div className="pg-table-wrap">
              <table className="data-table" aria-label="Planned calls">
                <thead><tr><th scope="col">Call</th><th scope="col" className="num">Times</th><th scope="col" className="num">Units</th><th scope="col">Pages</th></tr></thead>
                <tbody>
                  {plan.calls.map((r) => (
                    <tr key={r.call}><td>{r.call}</td><td className="num">{r.times}</td><td className="num">{r.units}</td><td>{r.pages}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        ) : null
      )}

      {stored && (
        <div className="pg-banner ok">
          <strong>Stored result found</strong>
          <div className="wrap-text">
            This PDF already has a stored result ({stored.facts} facts, {stored.created}). Opening it calls no model and shows the same facts.
          </div>
          <div style={{ marginTop: 4 }}>
            <Button variant="accent" onPress={() => n.selectRun(stored.run)}>Open the stored result</Button>
          </div>
        </div>
      )}
      <div className="pg-confirm">
        <strong>This calls the model</strong>
        <div className="body">Extracting calls the model and spends API tokens.{stored ? ' The stored result is kept.' : ''}</div>
        <Checkbox isSelected={n.confirmed} onChange={n.setConfirmed}>I understand this spends API tokens</Checkbox>
      </div>
      {status && !status.has_key && (
        <div className="pg-banner bad" role="alert">
          <strong>No API key</strong>
          <span>The API key is not set (in the environment or .env), so no run can start.</span>
        </div>
      )}
      {n.missing.length > 0 && <div className="pg-note">Still needed: {n.missing.join(', ')}.</div>}
      {n.startError && <ErrorBox message={n.startError} />}
      <div className="pg-actions">
        <Button variant={stored ? 'secondary' : 'accent'} isDisabled={!n.canStart} onPress={() => void n.start()}>
          {stored ? 'Extract again' : 'Start extraction'}
        </Button>
        {n.running && (
          <span className="pg-progress" role="status" aria-live="polite">
            <ProgressCircle aria-label="Extracting" isIndeterminate size="S" />
            Extracting... this takes a minute or two.{n.job ? ` ${Math.round(n.job.seconds)} s so far.` : ''}
          </span>
        )}
      </div>
    </div>
    </>
  );
}
