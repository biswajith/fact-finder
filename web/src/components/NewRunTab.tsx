import {
  Button, Checkbox, FileTrigger, InlineAlert, Heading, Content, Item, Picker, ProgressCircle, Radio, RadioGroup, TextField,
} from '@adobe/react-spectrum';
import * as api from '../api';
import { VOTES, type NewRun } from '../newRun';
import { useAsync } from '../hooks';
import { useRun } from '../store';
import { Empty, ErrorBox } from './common';

export function NewRunTab({ n }: { n: NewRun }) {
  const { status } = useRun();
  const pdfs = useAsync((signal) => api.getPdfs(signal), [], n.mode === 'pick');
  const plan = n.planOf;
  const stored = plan?.stored ?? null;
  const done = n.job?.status === 'done' ? n.job : null;
  const failed = n.job?.status === 'failed' ? n.job : null;

  return (
    <div className="panel">
      {done && (
        <InlineAlert variant="positive">
          <Heading>Run finished</Heading>
          <Content>
            <div className="wrap-text">{done.result}</div>
            {done.run && <div className="muted">Written to {done.run}. It is now the open run.</div>}
          </Content>
        </InlineAlert>
      )}
      {failed && (
        <InlineAlert variant="negative">
          <Heading>The run failed and nothing was written</Heading>
          <Content><span className="wrap-text">{failed.error}</span></Content>
        </InlineAlert>
      )}
      <div className="muted">Runs are written to runs/&lt;doc_id&gt;/&lt;run_id&gt;/ with facts.json, report.json and source.pdf.</div>
      <div className="form-col">
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
          <details className="card">
            <summary>Planned calls: {plan.total_calls} calls over {plan.units} units, sent together</summary>
            <div className="table-wrap">
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
        <InlineAlert variant="positive">
          <Heading>Stored result found</Heading>
          <Content>
            <div className="wrap-text">
              This PDF already has a stored result ({stored.facts} facts, {stored.created}). Opening it calls no model and shows the same facts.
            </div>
            <div style={{ marginTop: 8 }}>
              <Button variant="accent" onPress={() => n.selectRun(stored.run)}>Open the stored result</Button>
            </div>
          </Content>
        </InlineAlert>
      )}
      <InlineAlert variant="notice">
        <Heading>This calls the model</Heading>
        <Content>Extracting calls the model and spends API tokens.{stored ? ' The stored result is kept.' : ''}</Content>
      </InlineAlert>
      <Checkbox isSelected={n.confirmed} onChange={n.setConfirmed}>I understand this spends API tokens</Checkbox>
      {status && !status.has_key && (
        <InlineAlert variant="negative">
          <Heading>No API key</Heading>
          <Content>The API key is not set (in the environment or .env), so no run can start.</Content>
        </InlineAlert>
      )}
      {n.missing.length > 0 && <div className="muted">Still needed: {n.missing.join(', ')}.</div>}
      {n.startError && <ErrorBox message={n.startError} />}
      <div className="row">
        <Button variant={stored ? 'secondary' : 'accent'} isDisabled={!n.canStart} onPress={() => void n.start()}>
          {stored ? 'Extract again' : 'Start extraction'}
        </Button>
        {n.running && (
          <span className="row" role="status" aria-live="polite">
            <ProgressCircle aria-label="Extracting" isIndeterminate size="S" />
            Extracting... this takes about half a minute on a 50-page RFP.{n.job ? ` ${Math.round(n.job.seconds)} s so far.` : ''}
          </span>
        )}
      </div>
    </div>
  );
}
