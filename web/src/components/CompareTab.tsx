import { useEffect, useState } from 'react';
import { Item, Picker } from '@adobe/react-spectrum';
import * as api from '../api';
import { pct } from '../factsQuery';
import { useAsync } from '../hooks';
import { useRun } from '../store';
import type { CompareResponse, RunInfo } from '../types';
import { CATEGORY_NAMES } from '../types';
import { Empty, ErrorBox, Loading } from './common';
import { Stat } from './ReportTab';

const runLabel = (r: RunInfo) => `${r.run} · ${r.facts} facts`;

export function CompareTab() {
  const { run, runs } = useRun();
  const [a, setA] = useState(run);
  const [b, setB] = useState<string | null>(null);
  useEffect(() => setA(run), [run]);

  const docA = runs.find((r) => r.run === a)?.doc_id;
  const sameDoc = runs.filter((r) => r.run !== a && r.doc_id === docA);
  const bValid = b && sameDoc.some((r) => r.run === b) ? b : (sameDoc[0]?.run ?? null);

  const cmp = useAsync((signal) => api.getCompare(a, bValid as string, signal), [a, bValid], bValid !== null);

  return (
    <div className="panel">
      <div className="row" style={{ alignItems: 'flex-end', gap: 16 }}>
        <Picker label="Run A" selectedKey={a} onSelectionChange={(k) => setA(String(k))} items={runs} width="size-4600">
          {(r) => <Item key={r.run}>{runLabel(r)}</Item>}
        </Picker>
        {sameDoc.length === 0 ? (
          <Picker label="Run B" isDisabled placeholder="(no other run of this document)" width="size-4600">{[]}</Picker>
        ) : (
          <Picker label="Run B" selectedKey={bValid} onSelectionChange={(k) => setB(String(k))} items={sameDoc} width="size-4600">
            {(r) => <Item key={r.run}>{runLabel(r)}</Item>}
          </Picker>
        )}
      </div>
      {sameDoc.length === 0 ? (
        <Empty>There is no other run of this document to compare with. Run B is limited to runs of the same document ID{docA ? ` (${docA})` : ''}.</Empty>
      ) : cmp.loading && !cmp.data ? (
        <Loading label="Comparing" />
      ) : cmp.error ? (
        <ErrorBox message={cmp.error} onRetry={cmp.reload} />
      ) : cmp.data ? (
        <Result data={cmp.data} />
      ) : null}
    </div>
  );
}

function Result({ data }: { data: CompareResponse }) {
  const r = data.agreement;
  return (
    <>
      <div className="stats" role="list" aria-label="Agreement">
        <Stat label="Same sentences cited" value={pct(r.id_agreement)} hint={`${r.cited_both} IDs in both, of ${r.cited_ids[0]} and ${r.cited_ids[1]}`} />
        <Stat label="Same codes per sentence" value={pct(r.code_agreement)} hint={`${r.same_codes} of ${r.cited_both} shared IDs`} />
        <Stat label="Same fact IDs" value={pct(r.fact_id_agreement)} hint={`${r.same_fact_id} facts, of ${r.facts[0]} and ${r.facts[1]}`} />
      </div>
      <div className="muted">
        Exact figures: ID agreement {String(r.id_agreement)}, code agreement {String(r.code_agreement)}, fact ID agreement {String(r.fact_id_agreement)}.
        Runs made before 2026-11-18 hashed the wording into fact_id, so their fact ID agreement is near zero whatever the runs contain.
      </div>
      <h2 style={{ fontSize: 16, margin: 0 }}>Per category</h2>
      {Object.keys(r.by_category).length === 0 ? <Empty>None.</Empty> : (
        <div className="table-wrap">
          <table className="data-table" aria-label="Per category">
            <thead><tr><th scope="col">Code</th><th scope="col">Name</th><th scope="col" className="num">A</th><th scope="col" className="num">B</th><th scope="col" className="num">IDs in both</th></tr></thead>
            <tbody>
              {Object.entries(r.by_category).map(([c, x]) => (
                <tr key={c}><td>{c}</td><td>{CATEGORY_NAMES[c as keyof typeof CATEGORY_NAMES] ?? ''}</td><td className="num">{x.a}</td><td className="num">{x.b}</td><td className="num">{x.ids_both}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <h2 style={{ fontSize: 16, margin: 0 }}>Code differences</h2>
      {r.code_flips.length === 0 ? <Empty>No differences.</Empty> : (
        <div className="table-wrap">
          <table className="data-table" aria-label="Code differences">
            <thead><tr><th scope="col" className="num">IDs</th><th scope="col">Codes only in one run</th><th scope="col">Codes only in the other</th></tr></thead>
            <tbody>
              {r.code_flips.map(([[x, y], n], i) => (
                <tr key={i}><td className="num">{n}</td><td>{x || '-'}</td><td>{y || '-'}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <h2 style={{ fontSize: 16, margin: 0 }}>Source IDs filed under different codes</h2>
      {data.code_differences.length === 0 ? <Empty>No differences.</Empty> : (
        <div className="table-wrap">
          <table className="data-table" aria-label="Source IDs filed under different codes">
            <thead><tr><th scope="col">ID</th><th scope="col">Codes in A</th><th scope="col">Codes in B</th><th scope="col">Facts in A</th><th scope="col">Facts in B</th></tr></thead>
            <tbody>
              {data.code_differences.map((d) => (
                <tr key={d.id}><td>{d.id}</td><td>{d.codes_a}</td><td>{d.codes_b}</td><td>{d.facts_a}</td><td>{d.facts_b}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
