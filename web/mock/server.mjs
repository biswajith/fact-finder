// Dev-only mock of the backend API (WEB_UI_SPEC.md sections 4 to 6). Not part of the bundle.
// Usage: node mock/server.mjs   (port 8766, override with MOCK_PORT)
// Then: API_TARGET=http://127.0.0.1:8766 npm run dev
import http from 'node:http';

const PORT = Number(process.env.MOCK_PORT ?? 8766);
const cit = (id, page, section, text) => ({ id, page, page_label: String(page), section, text, bbox: [50, 80, 400, 110] });
const base = (id, category, text, citations, extra = {}) => ({
  fact_id: id, deal_id: 'demo', doc_id: 'rfp-demo', run_id: 'run_a', category, text, citations,
  unresolved_ids: [], flags: [], note: '', status: 'valid', source_call: 'A', problems: [], conflicts: [],
  origin: 'extracted', edited: false, deleted: false, original: null, resolution: null, corrections: [], votes: [], agreement: '', also: '',
  group_id: '', group_kind: '', group_title: '', ...extra,
});

const state = {
  facts: [
    base('f_0000000001', 'B', 'Buying organization is County of Demo, Department of General Services', [cit('p1.h1', 1, 'COUNTY OF DEMO', 'COUNTY OF DEMO')]),
    base('f_0000000002', 'D', 'Proposals are due 3 March 2027 at 2:00 PM Eastern', [cit('p3.1', 3, 'Schedule', 'Proposals must be received by March 3, 2027, 2:00 PM.')], { flags: ['mandatory'] }),
    base('f_0000000003', 'D', 'Questions are due 10 February 2027', [cit('p3.2', 3, 'Schedule', 'Questions: February 10, 2027.')]),
    base('f_0000000004', 'S', 'Submit one original and three copies to the Purchasing Office', [cit('p4.1', 4, 'Submission', 'Submit one original and three copies.'), cit('p5.2', 5, 'Submission', 'Late bids are rejected.')], { flags: ['mandatory'] }),
    base('f_0000000005', 'R', 'The vendor must carry professional liability insurance of 2 million dollars', [cit('p7.4', 7, 'Insurance', 'Vendor shall carry professional liability insurance of $2,000,000.')], { flags: ['mandatory', 'risk'] }),
    base('f_0000000006', 'C', 'The contract term is three years', [cit('p11.3', 11, 'Term', 'The term of the contract is three (3) years.')], { status: 'conflict', conflicts: ['f_0000000007'] }),
    base('f_0000000007', 'Q', 'The contract term is stated as both three years and five years', [cit('p11.3', 11, 'Term', 'The term of the contract is three (3) years.'), cit('p19.1', 19, 'Term', 'This agreement runs for five (5) years.')], { status: 'conflict', conflicts: ['f_0000000006'] }),
    base('f_0000000008', 'E', 'Price counts for 40 percent of the score', [cit('p9.2', 9, 'Evaluation', 'Cost proposal: 40 points.')]),
    base('f_0000000009', 'G', 'Bidder must be registered to do business in the state', [cit('p2.5', 2, 'Eligibility', 'Bidders must be registered in the state.')], { flags: ['mandatory'] }),
    base('f_0000000010', 'X', 'Bids without the signed non-collusion form are disqualified', [cit('p6.1', 6, 'Forms', 'Failure to include the form will disqualify the bid.')], { flags: ['mandatory'] }),
    base('f_0000000011', 'R', 'Insurance: professional liability of 2 million dollars', [cit('p7.4', 7, 'Insurance', 'Professional liability: $2,000,000.')], { group_id: 'g1', group_kind: 'list', group_title: 'Insurance the vendor must carry', flags: ['mandatory'], votes: ['R', 'R', 'R'], agreement: '3/3' }),
    base('f_0000000012', 'R', 'Insurance: general liability of 1 million dollars', [cit('p7.5', 7, 'Insurance', 'General liability: $1,000,000.')], { group_id: 'g1', group_kind: 'list', group_title: 'Insurance the vendor must carry', flags: ['mandatory'], votes: ['R', 'R', 'C'], agreement: '2/3' }),
    base('f_0000000013', 'R', 'Insurance: workers compensation as required by law', [cit('p7.6', 7, 'Insurance', 'Workers compensation as required by law.')], { group_id: 'g1', group_kind: 'list', group_title: 'Insurance the vendor must carry', votes: ['R', 'R', 'R'], agreement: '3/3' }),
    base('f_0000000014', 'S', 'Late bids are rejected', [cit('p5.2', 5, 'Submission', 'Late bids are rejected.')], { group_id: 'g2', group_kind: 'same', flags: ['risk'], also: 'X', problems: ['The cited text does not state a consequence for early bids.'], unresolved_ids: ['p99.9'] }),
    base('f_0000000015', 'S', 'Bids received after the deadline will not be considered', [cit('p12.1', 12, 'Instructions', 'Bids received after the deadline will not be considered.')], { group_id: 'g2', group_kind: 'same', status: 'needs_review' }),
    base('f_0000000016', 'D', 'The contract starts 30 days after award', [cit('p11.1', 11, 'Term', 'Work begins 30 days after award.')], { flags: ['post-award'] }),
    base('f_0000000017', 'R', 'The vendor must keep records for seven years after the contract ends', [cit('p15.2', 15, 'Records', 'Records must be kept for seven years.')], { flags: ['post-award', 'risk', 'unclear'] }),
  ],
  corrections: [],
  conflicts: [
    {
      id: 'q:f_0000000007', kind: 'source', title: 'The contract term is stated as both three years and five years',
      description: 'The document contradicts itself.', fact_ids: ['f_0000000007', 'f_0000000006'],
      options: [
        { label: 'Page 11: Term', text: 'The term of the contract is three (3) years.', citation: { id: 'p11.3', page: 11, page_label: '11', section: 'Term' }, changes: [] },
        { label: 'Page 19: Term', text: 'This agreement runs for five (5) years.', citation: { id: 'p19.1', page: 19, page_label: '19', section: 'Term' }, changes: [] },
      ],
      status: 'open', resolution: null,
    },
    {
      id: 'k_1a2b3c4d', kind: 'raised', title: 'Which date does the 3 March correction apply to?',
      description: 'Two facts mention 3 March.', fact_ids: ['f_0000000002', 'f_0000000003'],
      options: [
        { label: 'Proposal deadline', text: 'Change the proposal due date to 5 March.', changes: [{ op: 'edit', fact_id: 'f_0000000002', fields: { text: 'Proposals are due 5 March 2027 at 2:00 PM Eastern' } }] },
        { label: 'Question deadline', text: 'Change the question due date.', changes: [{ op: 'edit', fact_id: 'f_0000000003', fields: { text: 'Questions are due 5 February 2027' } }] },
      ],
      status: 'open', resolution: null,
    },
  ],
  sections: [
    { key: 'overview', title: 'Buyer and scope', cats: ['B'] },
    { key: 'dates', title: 'Key dates', cats: ['D'] },
    { key: 'gates', title: 'Go/no-go gates and disqualifiers', cats: ['G', 'X'] },
    { key: 'submission', title: 'How to submit', cats: ['S'] },
    { key: 'evaluation', title: 'How bids are scored', cats: ['E'] },
    { key: 'contract', title: 'Contract terms and risks', cats: ['C'] },
    { key: 'requirements', title: 'Requirements', cats: ['R'] },
  ].map((s) => ({ ...s, points: [], generated_at: null, hash: null, stale: false, updating: false, pinned: [], error: null })),
  chat: [],
  rebuild: new Set(),
};
// "dates" is already generated and covers only one fact.
Object.assign(state.sections[1], { points: [{ text: 'Bids are due 3 March 2027 at 2:00 PM Eastern.', fact_ids: ['f_0000000002'] }], generated_at: '2026-11-20T10:00:00Z' });

const live = () => state.facts.filter((f) => !f.deleted);
const sectionFacts = (s) => live().filter((f) => s.cats.includes(f.category));
const hash = (s) => JSON.stringify(sectionFacts(s).map((f) => [f.fact_id, f.text, f.flags])) + s.pinned.join();
state.sections[1].hash = hash(state.sections[1]);
const id = (p, n = 8) => p + Math.random().toString(16).slice(2, 2 + n).padEnd(n, '0');
const now = () => new Date().toISOString();

function sectionOut(s) {
  const f = sectionFacts(s);
  const cited = new Set(s.points.flatMap((p) => p.fact_ids));
  return {
    key: s.key, title: s.title, points: s.points, generated_at: s.generated_at,
    stale: s.generated_at !== null && s.hash !== hash(s), updating: state.rebuild.has(s.key), fact_count: f.length,
    uncovered: s.generated_at ? f.filter((x) => !cited.has(x.fact_id)).map((x) => x.fact_id) : [], pinned: s.pinned, error: s.error,
  };
}
const summaries = () => ({ sections: state.sections.map(sectionOut), updating: state.rebuild.size > 0 });
function startBuild(keys) {
  for (const s of state.sections.filter((x) => keys.includes(x.key))) {
    state.rebuild.add(s.key);
    setTimeout(() => {
      if (process.env.MOCK_NO_KEY) { s.error = 'OPENAI_API_KEY is not set'; }
      else {
        const f = sectionFacts(s);
        s.points = [...f.slice(0, 2), ...f.filter((x) => s.pinned.includes(x.fact_id))].map((x) => ({ text: x.text + '.', fact_ids: [x.fact_id] }));
        s.generated_at = now(); s.hash = hash(s); s.error = null;
      }
      state.rebuild.delete(s.key);
    }, 3500);
  }
}
const afterChange = () => startBuild(state.sections.filter((s) => s.generated_at && s.hash !== hash(s)).map((s) => s.key));

function log(entry) { const e = { id: id('c_'), at: now(), source: 'ui', fact_id: null, fields: null, reason: null, conflict_id: null, target: null, ...entry }; state.corrections.push(e); return e; }
function setFact(f, fields, c) {
  f.original = { ...(f.original ?? {}) };
  for (const [k, v] of Object.entries(fields)) { if (!(k in f.original)) f.original[k] = f[k]; f[k] = v; }
  f.edited = true; f.corrections.push(c.id);
}
function effectiveCorrections() { return state.corrections.map((c) => ({ ...c, undone: state.corrections.some((u) => u.op === 'undo' && u.target === c.id), fact_text: state.facts.find((f) => f.fact_id === c.fact_id)?.text ?? null })).reverse(); }
function undo(target) {
  const c = state.corrections.find((x) => x.id === target); if (!c) return;
  log({ op: 'undo', target });
  const f = state.facts.find((x) => x.fact_id === c.fact_id);
  if (c.op === 'delete' && f) f.deleted = false;
  if (c.op === 'add') state.facts = state.facts.filter((x) => x.fact_id !== c.fact_id);
  if (c.op === 'edit' && f) { for (const k of Object.keys(c.fields)) if (f.original && k in f.original) { f[k] = f.original[k]; delete f.original[k]; } if (!Object.keys(f.original ?? {}).length) { f.original = null; f.edited = false; } }
  if (c.op === 'resolve') { const cf = state.conflicts.find((x) => x.id === c.conflict_id); if (cf) { cf.status = 'open'; cf.resolution = null; } }
}

function resolve(cid, body) {
  const cf = state.conflicts.find((c) => c.id === cid); if (!cf) return null;
  const opt = body.option ?? null;
  cf.resolution = opt === null ? { option: null, label: 'Your answer', text: body.text, at: now() } : { option: opt, label: cf.options[opt].label, text: cf.options[opt].text, at: now() };
  cf.status = 'resolved';
  log({ op: 'resolve', conflict_id: cid, fields: opt === null ? { option: null, text: body.text } : { option: opt } });
  if (cf.kind === 'raised' && opt !== null) for (const ch of cf.options[opt].changes) { const c = log({ op: ch.op, fact_id: ch.fact_id, fields: ch.fields ?? null, conflict_id: cid }); const f = state.facts.find((x) => x.fact_id === ch.fact_id); if (f) ch.op === 'delete' ? (f.deleted = true) : setFact(f, ch.fields, c); }
  if (cf.kind === 'source') for (const fid of cf.fact_ids) { const f = state.facts.find((x) => x.fact_id === fid); if (f && f.status === 'conflict') f.status = 'valid'; }
  afterChange();
  return cf;
}

const runs = [
  { run: 'demo/run_a', doc_id: 'rfp-demo', run_id: 'run_a', facts: 17, modified: '2026-11-20T09:00:00Z', has_pdf: true, corrections: 0, pdf_name: 'source.pdf' },
  { run: 'demo/run_nopdf', doc_id: 'rfp-demo', run_id: 'run_nopdf', facts: 17, modified: '2026-11-19T09:00:00Z', has_pdf: false, corrections: 0, pdf_name: '' },
  { run: 'other/only_run', doc_id: 'rfp-other', run_id: 'only_run', facts: 4, modified: '2026-11-18T09:00:00Z', has_pdf: false, corrections: 0, pdf_name: '' },
];
const ownPdf = new Set(['demo/run_a']); // a run's own source.pdf cannot be removed

function pageSvg(page) {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="500" height="650"><rect width="500" height="650" fill="#fff" stroke="#999"/><rect x="50" y="80" width="350" height="30" fill="#ffe066" opacity=".6"/><text x="50" y="40" font-size="20" font-family="sans-serif">Mock PDF page ${page}</text></svg>`;
}

function chatScript(message, send) {
  const m = message.toLowerCase();
  const chunks = (t) => t.match(/.{1,12}/g) ?? [];
  const run = async () => {
    const wait = (ms) => new Promise((r) => setTimeout(r, ms));
    const tools = []; const conflict_ids = []; let text = '';
    const say = async (t) => { for (const c of chunks(t)) { text += c; send({ type: 'text', delta: c }); await wait(40); } };
    if (m.includes('error')) { send({ type: 'error', message: 'OPENAI_API_KEY is not set' }); return null; }
    send({ type: 'tool', name: 'search_facts', label: 'Searched the facts', ok: true }); tools.push({ name: 'search_facts', label: 'Searched the facts', ok: true }); await wait(400);
    if (m.includes('correct') || m.includes('change') || m.includes('march')) {
      const f = state.facts.find((x) => x.fact_id === 'f_0000000003');
      const c = log({ op: 'edit', source: 'chat', fact_id: f.fact_id, fields: { text: 'Questions are due 5 February 2027' }, reason: 'customer said so' });
      setFact(f, { text: 'Questions are due 5 February 2027' }, c);
      const t = { name: 'edit_fact', label: 'Changed fact f_0000000003', ok: true }; tools.push(t); send({ type: 'tool', ...t });
      send({ type: 'changed', what: ['facts', 'conflicts', 'summaries'] }); afterChange();
      send({ type: 'conflict', conflict_id: 'k_1a2b3c4d' }); conflict_ids.push('k_1a2b3c4d');
      await say('I changed [f_0000000003]. The proposal deadline [f_0000000002] also mentions 3 March, so please choose which one you meant. Here is the markup <b>not bold</b>.');
    } else {
      await say('The proposals are due on 3 March 2027, see [f_0000000002]. A user fact would look like [u_0123456789].');
    }
    return { id: id('m_'), role: 'assistant', at: now(), text, tools, conflict_ids };
  };
  return run();
}


// ---- Spec 11.1 routes -------------------------------------------------------------------
const CATEGORIES = ['B', 'C', 'G', 'X', 'D', 'S', 'E', 'R', 'Q'];
const withComputed = (f) => ({ ...f, post_award: f.flags.includes('post-award'), affects_bid: f.flags.includes('post-award') && (f.flags.includes('risk') || /\d\s*(million|percent|%)|\$\d/.test(f.text)), split: new Set(f.votes).size > 1 });
const inView = (f, view) => (view === 'Bid' ? !f.post_award || f.affects_bid : view === 'After award' ? f.post_award : true);
const pageNo = (f) => Math.min(...f.citations.map((c) => c.page), 999);
const ordered = (fs) => [...fs].sort((a, b) => pageNo(a) - pageNo(b) || a.fact_id.localeCompare(b.fact_id));
const list = (v) => (v ? v.split(',').filter(Boolean) : []);
function filtered(sp, skipCategories) {
  const q = (sp.get('q') ?? '').trim().toLowerCase(), cats = list(sp.get('categories')), st = list(sp.get('statuses')), fl = list(sp.get('flags'));
  const from = Number(sp.get('page_from') || 0), to = Number(sp.get('page_to') || 0), view = sp.get('view') || 'All';
  return state.facts.map(withComputed).filter((f) => {
    if (f.deleted && !sp.get('include_deleted')) return false;
    if (sp.get('edited') && !(f.edited || f.origin === 'user' || f.deleted)) return false;
    if (!inView(f, view)) return false;
    if (sp.get('split_only') && !f.split) return false;
    if (!skipCategories && cats.length && !cats.includes(f.category)) return false;
    if (st.length && !st.includes(f.status)) return false;
    if (fl.length && !fl.some((x) => f.flags.includes(x))) return false;
    if (q && !f.text.toLowerCase().includes(q) && !f.citations.some((c) => c.text.toLowerCase().includes(q))) return false;
    if (from && !f.citations.some((c) => c.page >= from && c.page <= to)) return false;
    return true;
  });
}
function itemsOf(fs) {
  const members = {}; for (const f of fs) if (f.group_id) (members[f.group_id] ??= []).push(f);
  const out = [], done = new Set();
  for (const f of fs) {
    if (!f.group_id || members[f.group_id].length < 2) out.push({ kind: 'fact', fact_ids: [f.fact_id] });
    else if (!done.has(f.group_id)) { done.add(f.group_id); out.push({ kind: f.group_kind || 'list', fact_ids: members[f.group_id].map((x) => x.fact_id) }); }
  }
  return out;
}
const pageLabels = (f) => [...new Set(f.citations.map((c) => c.page_label))].join('; ');
function entriesOf(fs) {
  return itemsOf(ordered(fs)).map((it) => {
    const m = it.fact_ids.map((id) => fs.find((f) => f.fact_id === id));
    if (it.kind === 'list') return { text: m[0].group_title, page: [...new Set(m.flatMap((f) => f.citations.map((c) => c.page_label)))].join('; '), children: m.map((f) => ({ text: f.text, page: pageLabels(f) })) };
    return { text: m[0].text, page: [...new Set(m.flatMap((f) => f.citations.map((c) => c.page_label)))].join('; '), children: [] };
  });
}
function overview(view) {
  const fs = state.facts.filter((f) => !f.deleted).map(withComputed).filter((f) => inView(f, view));
  const of = (c) => fs.filter((f) => f.category === c);
  const dated = of('D').filter((f) => /\d{4}/.test(f.text)).map((f) => {
    const m = f.text.match(/(\d+) (\w+) (\d{4})/); const d = new Date(`${m[1]} ${m[2]} ${m[3]} 12:00 UTC`);
    const t = f.text.match(/at (\d+:\d+ [AP]M)/);
    return { date: d.toISOString().slice(0, 10), label: d.toUTCString().replace(/^(\w+), (\d+) (\w+) (\d+).*/, '$1 $2 $3 $4'), time: t ? t[1] : '', text: f.text, page: pageLabels(f) };
  }).sort((a, b) => a.date.localeCompare(b.date));
  const withBrief = view !== 'After award';
  return {
    overview: {
      summary: {
        submission: withBrief ? [{ row: 'Where to send it', text: 'Purchasing Office, one original and three copies', page: '4' }, { row: 'Format', text: '', page: '' }] : [],
        gates: [], scoring: withBrief ? [{ row: 'Price', text: 'Price counts for 40 percent of the score', page: '9' }] : [],
        questions: [],
      },
      buyer: withBrief ? [{ row: 'Buyer', text: 'County of Demo, Department of General Services', page: '1' }, { row: 'Contact', text: '', page: '' }] : [],
      buyer_facts: entriesOf(of('B')), gates: entriesOf(of('G')), disqualifiers: entriesOf(of('X')), submission: entriesOf(of('S')),
      contradictions: of('Q').map((f) => ({ text: f.text, page: f.citations.map((c) => c.page_label).join(' vs '), children: [] })),
      unclear: entriesOf(fs.filter((f) => f.flags.includes('unclear') && f.category !== 'Q')),
      scoring: entriesOf(of('E')),
      calendar: { dated, undated: of('D').filter((f) => !/\d{4}/.test(f.text)).map((f) => ({ text: f.text, page: pageLabels(f) })) },
    },
    counts: { needs_review: fs.filter((f) => f.status === 'needs_review').length, conflicts: fs.filter((f) => f.status === 'conflict').length, risk: fs.filter((f) => f.flags.includes('risk')).length, mandatory: fs.filter((f) => f.flags.includes('mandatory')).length, unclear: fs.filter((f) => f.flags.includes('unclear')).length },
    by_category: Object.fromEntries(CATEGORIES.filter((c) => of(c).length).map((c) => [c, of(c).length])),
    has_post_award: state.facts.some((f) => f.flags.includes('post-award')),
    views: ['All', 'Bid', 'After award'],
  };
}
const csvCell = (v) => `"${String(v).replace(/"/g, '""')}"`;
const report = () => ({
  run_id: 'run_a', pages: 20, facts: 17, seconds: { extract: 30.96, sweep_and_check: 13.46, total: 44.44 }, output_tokens: 35149, cache_hit_calls_2_to_n: 0.039,
  failed_calls: ['LABEL2'], incomplete_calls: ['LABEL3'], units_unanswered_votes: 2,
  calls: [
    { name: 'LABEL1', kind: 'label', status: 'ok', seconds: 11.18, lines: 29, usage: { output_tokens: 4100 }, retries: 0, log: ['END says 28 lines, got 29'], output: 'B|Buying organization is County of Demo|p1.h1|\nD|Proposals are due 3 March 2027 <b>not bold</b>|p3.1|' },
    { name: 'LABEL2', kind: 'label', status: 'failed', seconds: 3.2, lines: 0, usage: { output_tokens: 0 }, retries: 2, log: [], output: '' },
    { name: 'LABEL3', kind: 'label', status: 'ok', seconds: 9.5, lines: 12, usage: { output_tokens: 2000 }, retries: 1, log: ['asked again', 'still short'], output: 'R|The vendor must carry insurance|p7.4|' },
    { name: 'STATE1', kind: 'state', status: 'ok', seconds: 14.1, lines: 40, usage: { output_tokens: 9000 }, retries: 0, log: [], output: '(state output)' },
  ],
});
const runsTable = () => runs.map((r, i) => ({ run: r.run, document: r.doc_id, facts: r.facts, 'total s': i === 0 ? 44.4 : i === 1 ? 51.9 : null, 'extract s': i === 0 ? 31 : i === 1 ? 35 : null, 'sweep and check s': i === 0 ? 13.4 : i === 1 ? 16.9 : null, 'output tokens': i < 2 ? 35149 : null, finished: r.modified.slice(0, 16).replace('T', ' ') }));
const jobs = new Map();
const uploads = new Map();
const PDFS = [{ path: 'rfp-demo.pdf', name: 'rfp-demo.pdf' }, { path: 'samples/other rfp.pdf', name: 'other rfp.pdf' }];
const readRaw = (req) => new Promise((r) => { const c = []; req.on('data', (d) => c.push(d)); req.on('end', () => r(Buffer.concat(c))); });

async function newRoutes(req, res, url, p, m) {
  const sp = url.searchParams;
  if (p === '/runs/table') return json(res, 200, runsTable());
  if (p === '/pdfs') return json(res, 200, PDFS);
  if (p === '/compare') {
    const a = runs.find((r) => r.run === sp.get('a')), b = runs.find((r) => r.run === sp.get('b'));
    if (!a || !b) return json(res, 404, { detail: 'run not found' });
    if (a.doc_id !== b.doc_id) return json(res, 400, { detail: 'These runs are of different documents.' });
    return json(res, 200, {
      agreement: { facts: [a.facts, b.facts], cited_ids: [212, 208], cited_both: 190, id_agreement: 0.8636, same_codes: 171, code_agreement: 0.9, same_fact_id: 3, fact_id_agreement: 0.0058, by_category: { D: { a: 12, b: 11, ids_both: 10 }, R: { a: 80, b: 84, ids_both: 70 }, S: { a: 5, b: 5, ids_both: 5 } }, code_flips: [[['R', 'C'], 12], [['G', 'X'], 4], [['', 'Q'], 1]] },
      code_differences: [{ id: 'p7.4', codes_a: 'R', codes_b: 'C', facts_a: 'Vendor must carry insurance', facts_b: 'Insurance is part of the contract' }, { id: 'p9.2', codes_a: 'E', codes_b: 'ER', facts_a: 'Price counts 40 percent', facts_b: 'Price counts 40 percent / Price must be firm' }],
    });
  }
  if (p === '/uploads' && m === 'POST') {
    const body = await readRaw(req); if (!body.length) return json(res, 400, { detail: 'empty upload' });
    const id = 'up_' + Math.random().toString(16).slice(2, 8); const info = { upload_id: id, name: sp.get('name') || 'upload.pdf', pages: 12 };
    uploads.set(id, info); return json(res, 200, info);
  }
  if (p === '/extract/plan' && m === 'POST') {
    const b = await readBody(req); if (!b.path && !b.upload_id) return json(res, 400, { detail: 'path or upload_id' });
    await new Promise((r) => setTimeout(r, 400));
    const calls = [{ call: 'LABEL1', times: b.votes, units: 120, pages: '1-9' }, { call: 'LABEL2', times: b.votes, units: 118, pages: '9-20' }, { call: 'STATE1', times: 1, units: 238, pages: '1-20' }, { call: 'CHECK', times: 1, units: 238, pages: '1-20' }];
    return json(res, 200, { calls, total_calls: calls.reduce((n, c) => n + c.times, 0), units: 238, stored: b.doc_id === 'stored' ? { run: 'demo/run_a', facts: 17, created: '2026-11-20 09:00' } : null });
  }
  if (p === '/extract' && m === 'POST') {
    const b = await readBody(req);
    if (b.confirm !== true) return json(res, 400, { detail: 'confirm is required' });
    if (process.env.MOCK_NO_KEY) return json(res, 400, { detail: 'The API key is not set.' });
    if (!b.deal_id || !b.doc_id) return json(res, 400, { detail: 'deal ID and doc ID are required' });
    if ([...jobs.values()].some((j) => j.status === 'running')) return json(res, 409, { detail: 'An extraction is already running.' });
    const jid = 'job_' + Math.random().toString(16).slice(2, 8);
    const job = { status: 'running', started: Date.now(), result: null, run: null, error: null, doc_id: b.doc_id };
    jobs.set(jid, job);
    setTimeout(() => {
      if (b.doc_id === 'fail') { job.status = 'failed'; job.error = 'RuntimeError: the model returned nothing'; return; }
      const run_id = 'run_2026_11_20_' + jid.slice(4);
      runs.unshift({ run: `${b.doc_id}/${run_id}`, doc_id: b.doc_id, run_id, facts: 17, modified: now(), has_pdf: true, corrections: 0, pdf_name: 'source.pdf' });
      ownPdf.add(`${b.doc_id}/${run_id}`);
      job.status = 'done'; job.run = `${b.doc_id}/${run_id}`; job.result = '17 facts from 238 units in 5.1 s: 15 with all 3 votes agreed, 2 split; failed calls []';
    }, 5000);
    return json(res, 200, { job_id: jid });
  }
  let mm;
  if ((mm = p.match(/^\/extract\/([^/]+)$/)) && m === 'GET') {
    const j = jobs.get(mm[1]); if (!j) return json(res, 404, { detail: 'job not found' });
    return json(res, 200, { status: j.status, seconds: (Date.now() - j.started) / 1000, result: j.result, run: j.run, error: j.error });
  }
  return false;
}

const json = (res, code, body) => { res.writeHead(code, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(body)); };
const readBody = (req) => new Promise((r) => { let s = ''; req.on('data', (d) => (s += d)); req.on('end', () => r(s ? JSON.parse(s) : {})); });

http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://x');
  const p = url.pathname.replace(/^\/api/, '');
  const run = url.searchParams.get('run');
  const m = req.method;
  try {
    if (p === '/status') return json(res, 200, { model: 'mock-model', has_key: !process.env.MOCK_NO_KEY, runs_folder: '/mock/runs' });
    if (p === '/runs') return json(res, 200, runs);
    if (['/runs/table', '/pdfs', '/compare', '/uploads', '/extract/plan', '/extract'].includes(p) || p.startsWith('/extract/')) {
      if ((await newRoutes(req, res, url, p, m)) !== false) return;
    }
    if (!run || !runs.some((r) => r.run === run)) return json(res, 404, { detail: 'run not found' });
    let mm;
    if (p === '/overview') return json(res, 200, overview(url.searchParams.get('view') || 'All'));
    if (p === '/facts/list') {
      const fs = ordered(filtered(url.searchParams, false));
      const others = filtered(url.searchParams, true);
      return json(res, 200, { total: fs.length, by_category: Object.fromEntries(CATEGORIES.filter((c) => others.some((f) => f.category === c)).map((c) => [c, others.filter((f) => f.category === c).length])), items: itemsOf(fs), facts: fs });
    }
    if (p === '/facts.csv') {
      const fs = ordered(filtered(url.searchParams, false));
      res.writeHead(200, { 'Content-Type': 'text/csv; charset=utf-8', 'Content-Disposition': 'attachment; filename="rfp-demo_run_a.csv"' });
      return res.end('category,text,flags,pages\n' + fs.map((f) => [f.category, f.text, f.flags.join(' '), pageLabels(f)].map(csvCell).join(',')).join('\n') + '\n');
    }
    if (p === '/report') {
      if (run === 'demo/run_nopdf' || run === 'other/only_run') return json(res, 404, { detail: 'this run has no report' });
      return json(res, 200, report());
    }
    if (p === '/pdf') {
      const r = runs.find((x) => x.run === run);
      if (m === 'PUT') {
        if (ownPdf.has(run)) return json(res, 400, { detail: 'this run has its own source.pdf' });
        let name;
        if ((req.headers['content-type'] ?? '').startsWith('application/pdf')) { await readRaw(req); name = url.searchParams.get('name') || 'upload.pdf'; }
        else { const b = await readBody(req); if (!PDFS.some((x) => x.path === b.path)) return json(res, 400, { detail: 'not one of the PDFs' }); name = PDFS.find((x) => x.path === b.path).name; }
        r.has_pdf = true; r.pdf_name = name; return json(res, 200, { has_pdf: true, name });
      }
      if (m === 'DELETE') { if (!ownPdf.has(run)) { r.has_pdf = false; r.pdf_name = ''; } return json(res, 200, { has_pdf: ownPdf.has(run) }); }
    }
    if (p === '/facts' && m === 'GET') return json(res, 200, { doc_id: 'rfp-demo', run_id: 'run_a', pages: 20, facts: state.facts.filter((f) => url.searchParams.get('include_deleted') || !f.deleted).map(withComputed) });
    if (p === '/facts' && m === 'POST') {
      const b = await readBody(req); const f = base(id('u_', 10), b.category, b.text, [], { origin: 'user', flags: b.flags ?? [], note: b.note ?? '' });
      const c = log({ op: 'add', fact_id: f.fact_id, fields: b }); f.corrections.push(c.id); state.facts.push(f); afterChange(); return json(res, 200, f);
    }
    if ((mm = p.match(/^\/facts\/([^/]+)(\/restore)?$/))) {
      const f = state.facts.find((x) => x.fact_id === mm[1]); if (!f) return json(res, 404, { detail: 'fact not found' });
      if (m === 'PATCH') { const b = await readBody(req); const { reason, ...fields } = b; const c = log({ op: 'edit', fact_id: f.fact_id, fields, reason }); setFact(f, fields, c); afterChange(); return json(res, 200, f); }
      if (m === 'DELETE') { log({ op: 'delete', fact_id: f.fact_id }); f.deleted = true; afterChange(); return json(res, 200, { ok: true }); }
      if (m === 'POST') { for (const c of state.corrections.filter((x) => x.fact_id === f.fact_id && x.op !== 'undo' && !effectiveCorrections().find((e) => e.id === x.id).undone)) undo(c.id); afterChange(); return json(res, 200, f); }
    }
    if (p === '/corrections') return json(res, 200, effectiveCorrections());
    if ((mm = p.match(/^\/corrections\/([^/]+)\/undo$/))) { undo(mm[1]); afterChange(); return json(res, 200, { ok: true }); }
    if (p === '/conflicts') return json(res, 200, [...state.conflicts].sort((a, b) => (a.status === 'resolved') - (b.status === 'resolved')));
    if ((mm = p.match(/^\/conflicts\/([^/]+)\/resolve$/))) { const c = resolve(decodeURIComponent(mm[1]), await readBody(req)); return c ? json(res, 200, c) : json(res, 404, { detail: 'conflict not found' }); }
    if ((mm = p.match(/^\/conflicts\/([^/]+)\/reopen$/))) { const c = state.conflicts.find((x) => x.id === decodeURIComponent(mm[1])); if (!c) return json(res, 404, { detail: 'conflict not found' }); const last = [...state.corrections].reverse().find((x) => x.op === 'resolve' && x.conflict_id === c.id); if (last) undo(last.id); return json(res, 200, c); }
    if (p === '/summaries') return json(res, 200, summaries());
    if (p === '/summaries/generate') { const b = await readBody(req); startBuild(b.sections ?? state.sections.map((s) => s.key)); return json(res, 200, summaries()); }
    if (p === '/summaries/pin') { const b = await readBody(req); for (const s of state.sections) for (const fid of b.fact_ids) { const f = state.facts.find((x) => x.fact_id === fid); if (f && s.cats.includes(f.category)) s.pinned = b.pinned ? [...new Set([...s.pinned, fid])] : s.pinned.filter((x) => x !== fid); } afterChange(); return json(res, 200, summaries()); }
    if (p === '/page') { if (!runs.find((r) => r.run === run).has_pdf) return json(res, 404, { detail: 'no PDF for this run' }); res.writeHead(200, { 'Content-Type': 'image/svg+xml' }); return res.end(pageSvg(url.searchParams.get('page'))); }
    if (p === '/chat' && m === 'GET') return json(res, 200, state.chat);
    if (p === '/chat' && m === 'DELETE') { state.chat = []; return json(res, 200, { ok: true }); }
    if (p === '/chat' && m === 'POST') {
      const b = await readBody(req);
      state.chat.push({ id: id('m_'), role: 'user', at: now(), text: b.message });
      res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' });
      const send = (o) => res.write(`data: ${JSON.stringify(o)}\n\n`);
      const msg = await chatScript(b.message, send);
      if (msg) { state.chat.push(msg); send({ type: 'done', message: msg }); }
      return res.end();
    }
    json(res, 404, { detail: 'not found' });
  } catch (e) { json(res, 400, { detail: String(e) }); }
}).listen(PORT, '127.0.0.1', () => console.log(`mock API on http://127.0.0.1:${PORT}`));
