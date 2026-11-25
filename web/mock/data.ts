/** Made-up data for the intake mock. Nothing here comes from a server or a model. */

export type Format = 'pdf' | 'word' | 'sheet' | 'json' | 'text';
export type DocType = 'rfp' | 'reissued-rfp' | 'change-addendum' | 'qa-addendum' | 'fill-in-template' | 'call-transcript' | 'deal-notes';
export type Side = 'buyer' | 'ours' | 'other' | '';
export type Phase = 'uploading' | 'reading' | 'classifying' | 'speakers' | 'review' | 'confirmed' | 'failed';

export interface DocTypeInfo {
  key: DocType;
  label: string;
  description: string;
  role: 'base' | 'change' | 'context';
  spoken: boolean;
  /** Where its facts sit on the priority ladder. */
  level: string;
  internal: boolean;
}

export const DOC_TYPES: DocTypeInfo[] = [
  { key: 'rfp', label: 'RFP', description: 'The request for proposals from the buyer: the full document, issued once.', role: 'base', spoken: false, level: 'Buyer, binding', internal: false },
  { key: 'reissued-rfp', label: 'Reissued RFP', description: 'A full RFP issued again after an earlier issue.', role: 'base', spoken: false, level: 'Buyer, binding', internal: false },
  { key: 'change-addendum', label: 'Change addendum', description: 'Changes an earlier buyer document: new dates, replaced or removed text.', role: 'change', spoken: false, level: 'Buyer, binding', internal: false },
  { key: 'qa-addendum', label: 'Q&A addendum', description: "Bidders' questions with the buyer's answers.", role: 'change', spoken: false, level: 'Buyer, binding', internal: false },
  { key: 'fill-in-template', label: 'Fill-in template', description: 'A form or sheet the bidder fills in and returns: price sheet, response matrix.', role: 'base', spoken: false, level: 'Buyer, binding', internal: false },
  { key: 'call-transcript', label: 'Call transcript', description: 'A live call between buyer and bidder. Each line has a speaker.', role: 'context', spoken: true, level: 'By speaker', internal: true },
  { key: 'deal-notes', label: 'Deal notes', description: 'Our own notes on the deal: CRM fields, capture notes, guesses and to-dos.', role: 'context', spoken: false, level: 'Our view', internal: true },
];

export const typeInfo = (t: DocType) => DOC_TYPES.find((d) => d.key === t) as DocTypeInfo;

export interface Speaker {
  id: string;
  name: string;
  organisation: string;
  title: string;
  /** The model's proposal, and why. */
  proposed: Side;
  why: string;
  side: Side;
  actsFor: '' | 'buyer' | 'ours';
  lines: number;
}

export interface Line {
  speaker: string; // '' for a line no one speaks
  time: string;
  text: string;
}

export interface Proposal {
  type: DocType;
  number: number | null;
  date: string | null;
  /** 0..1; null when the rules, not the model, proposed it. */
  confidence: number | null;
  /** What the model read that made it say so. */
  evidence: string;
  by: 'model' | 'rules';
}

export interface Doc {
  id: string;
  no: number;
  name: string;
  format: Format;
  size: number;
  pages: number;
  phase: Phase;
  progress: number;
  error: string | null;
  proposal: Proposal;
  type: DocType;
  number: number | null;
  date: string | null;
  replaces: string | null;
  confirmed: boolean;
  preview: string[];
  transcript: Line[];
  speakers: Speaker[];
  speakersConfirmed: boolean;
  units: number;
}

export interface Person {
  name: string;
  role: string;
}

export interface BidSummary {
  id: string;
  name: string;
  customer: string;
  due: string;
  documents: number;
  stage: 'Intake' | 'Reading' | 'Ready' | 'Submitted';
  owner: string;
  updated: string;
}

export const EXISTING_BIDS: BidSummary[] = [
  { id: 'ulster', name: 'Actuarial services RFP-UC26-039', customer: 'Ulster County', due: '2026-09-02', documents: 6, stage: 'Ready', owner: 'Tom Okafor', updated: '2 days ago' },
  { id: 'durham', name: 'Benefits consulting 24-117', customer: 'Durham County', due: '2024-08-19', documents: 4, stage: 'Submitted', owner: 'Priya Raman', updated: 'Aug 2024' },
  { id: 'marlow', name: 'Records management platform', customer: 'Town of Marlow', due: '2027-01-15', documents: 2, stage: 'Intake', owner: 'Tom Okafor', updated: '3 hours ago' },
  { id: 'kent', name: 'Fleet telematics renewal', customer: 'Kent Water Authority', due: '2026-12-04', documents: 9, stage: 'Reading', owner: 'Lena Voss', updated: 'just now' },
];

export const CUSTOMERS = ['Ulster County', 'Durham County', 'Town of Marlow', 'Kent Water Authority', 'City of Albany', 'Hudson Valley Transit'];
export const PEOPLE: Person[] = [
  { name: 'Tom Okafor', role: 'Bid manager' },
  { name: 'Priya Raman', role: 'Principal' },
  { name: 'Lena Voss', role: 'Solution lead' },
  { name: 'Marco Ruiz', role: 'Pricing' },
  { name: 'Aisha Grant', role: 'Proposal writer' },
];

// --- the sample bid -------------------------------------------------------------------------------

const CALL: Line[] = [
  { speaker: '', time: '', text: 'Capture call - Albany Transit Hub CCTV - Microsoft Teams - recorded and transcribed' },
  { speaker: '', time: '', text: 'May 27, 2027, 10:02 AM' },
  { speaker: 'Tom Okafor', time: '0:04', text: 'Morning all, thanks for making the time. I know the addendum only went out last week.' },
  { speaker: 'Dana Pike', time: '0:11', text: 'Sure. Anything formal still has to go through Purchasing in writing, this is just so we are not talking past each other.' },
  { speaker: 'Dana Pike', time: '0:19', text: 'Just to confirm, proposals are now due June 24 at 2 PM Eastern.' },
  { speaker: 'Lena Voss', time: '0:31', text: 'Is the contract budget capped at ninety thousand, or is that a guide?' },
  { speaker: 'Raj Mehta', time: '0:38', text: 'It is capped. Council approved ninety for year one.' },
  { speaker: 'Ann Lee', time: '0:47', text: 'From the advisory side, the county will weight the transition plan heavily. I would put real detail there.' },
  { speaker: 'Dana Pike', time: '1:02', text: 'I think hand delivery to the clerk would probably be fine too, but do not hold me to that.' },
  { speaker: 'Tom Okafor', time: '1:15', text: 'Understood. We will send our list of questions on Friday.' },
];

const SAMPLE_SPEAKERS: Speaker[] = [
  { id: 'Tom Okafor', name: 'Tom Okafor', organisation: 'Halvard Systems', title: 'Bid manager', proposed: 'ours', why: 'On your team list', side: '', actsFor: '', lines: 2 },
  { id: 'Dana Pike', name: 'Dana Pike', organisation: 'City of Albany', title: 'Purchasing', proposed: 'buyer', why: 'Named as the contact in the RFP', side: '', actsFor: '', lines: 3 },
  { id: 'Lena Voss', name: 'Lena Voss', organisation: 'Halvard Systems', title: 'Solution lead', proposed: 'ours', why: 'On your team list', side: '', actsFor: '', lines: 1 },
  { id: 'Raj Mehta', name: 'Raj Mehta', organisation: 'City of Albany', title: 'Finance', proposed: 'buyer', why: 'Speaks for the council budget', side: '', actsFor: '', lines: 1 },
  { id: 'Ann Lee', name: 'Ann Lee', organisation: 'Fenwick Advisory', title: '', proposed: 'other', why: "Says she advises the county", side: '', actsFor: 'buyer', lines: 1 },
];

const CALL2: Line[] = [
  { speaker: '', time: '', text: 'Clarification call - RFP 2027-04 Transit Hub CCTV' },
  { speaker: '', time: '', text: 'June 3, 2027 - Microsoft Teams - transcript' },
  { speaker: 'Dana Pike', time: '0:02', text: 'Thanks for joining. I have Kevin from IT on the line as well.' },
  { speaker: '+1 518 555 0143', time: '0:09', text: 'Hi, Kevin here, I look after the camera network at the hub.' },
  { speaker: 'Marco Ruiz', time: '0:15', text: 'Thanks Kevin. On the price form, are option years priced per camera or as a lump sum?' },
  { speaker: 'Dana Pike', time: '0:24', text: 'Per camera. We will put that in writing in the next addendum.' },
  { speaker: '+1 518 555 0143', time: '0:33', text: 'And the existing fibre stays. You would not need to pull new cable to the platforms.' },
  { speaker: 'Tom Okafor', time: '0:41', text: 'That helps a lot. We will reflect it in the transition plan.' },
  { speaker: 'Marco Ruiz', time: '0:48', text: 'One more: is there a cap on the monitoring rate in year two?' },
  { speaker: 'Dana Pike', time: '0:55', text: 'No cap, but the council will compare it with year one.' },
];

const CALL2_SPEAKERS: Speaker[] = [
  { id: 'Dana Pike', name: 'Dana Pike', organisation: 'City of Albany', title: 'Purchasing', proposed: 'buyer', why: 'Named as the contact in the RFP', side: '', actsFor: '', lines: 3 },
  { id: '+1 518 555 0143', name: '+1 518 555 0143', organisation: '', title: '', proposed: '', why: 'Joined by phone; says "Kevin from IT"', side: '', actsFor: '', lines: 2 },
  { id: 'Marco Ruiz', name: 'Marco Ruiz', organisation: 'Halvard Systems', title: 'Pricing', proposed: 'ours', why: 'Asks the buyer about pricing for the bid', side: '', actsFor: '', lines: 2 },
  { id: 'Tom Okafor', name: 'Tom Okafor', organisation: 'Halvard Systems', title: 'Bid manager', proposed: 'ours', why: 'On your team list', side: '', actsFor: '', lines: 1 },
];

interface Sample {
  name: string;
  format: Format;
  size: number;
  pages: number;
  units: number;
  proposal: Proposal;
  preview: string[];
  transcript?: Line[];
  speakers?: Speaker[];
}

export const SAMPLES: Sample[] = [
  {
    name: 'RFP-2027-04 Transit Hub CCTV.pdf', format: 'pdf', size: 6075, pages: 4, units: 52,
    proposal: { type: 'rfp', number: null, date: '2027-05-03', confidence: 0.97, by: 'model', evidence: '"REQUEST FOR PROPOSALS No. 2027-04 ... Issue date: May 3, 2027" on page 1.' },
    preview: ['CITY OF ALBANY - DEPARTMENT OF GENERAL SERVICES', 'REQUEST FOR PROPOSALS No. 2027-04', 'Transit Hub CCTV Replacement and Monitoring', 'Issue date: May 3, 2027', 'Proposals due: June 10, 2027, 2:00 PM Eastern'],
  },
  {
    name: 'Addendum 1.pdf', format: 'pdf', size: 3550, pages: 2, units: 14,
    proposal: { type: 'change-addendum', number: 1, date: '2027-05-20', confidence: 0.95, by: 'model', evidence: '"ADDENDUM NO. 1 ... Issued May 20, 2027" and "the due date is changed to June 24".' },
    preview: ['ADDENDUM NO. 1 to RFP No. 2027-04', 'Issued May 20, 2027', 'The proposal due date is changed to June 24, 2027 at 2:00 PM Eastern.', 'Section 2.1, Format of Proposals, is replaced in full by the following.'],
  },
  {
    name: 'Addendum 2 - Questions and answers.docx', format: 'word', size: 37113, pages: 1, units: 14,
    proposal: { type: 'qa-addendum', number: 2, date: null, confidence: 0.88, by: 'model', evidence: '"Addendum 2 - Responses to bidder questions"; no issue date found in the document.' },
    preview: ['Addendum 2 - Responses to bidder questions', 'Q1. May bidders propose a phased cut-over?', 'A1. Yes. Describe each phase in the transition plan.', 'Q2. Is on-site storage of footage required?'],
  },
  {
    name: 'Attachment C - Price form.xlsx', format: 'sheet', size: 5218, pages: 1, units: 9,
    proposal: { type: 'fill-in-template', number: null, date: '2027-05-03', confidence: 0.91, by: 'model', evidence: 'A sheet of blank price cells under "Year 1", "Year 2", "Option years".' },
    preview: ['Item | Unit | Year 1 | Year 2 | Option year 1', 'Camera replacement | each | | |', 'Monitoring service | month | | |'],
  },
  {
    name: 'Capture call 2027-05-27.pdf', format: 'pdf', size: 5314, pages: 2, units: 22,
    proposal: { type: 'call-transcript', number: null, date: '2027-05-27', confidence: 0.93, by: 'model', evidence: 'A Teams transcript: names with time stamps, conversational lines, dated May 27, 2027.' },
    preview: CALL.slice(0, 5).map((l) => (l.speaker ? `${l.speaker}  ${l.time}  ${l.text}` : l.text)),
    transcript: CALL,
    speakers: SAMPLE_SPEAKERS,
  },
  {
    name: 'Deal notes - Albany CCTV.md', format: 'text', size: 642, pages: 1, units: 16,
    proposal: { type: 'deal-notes', number: null, date: '2027-06-01', confidence: 0.9, by: 'model', evidence: 'CRM fields ("Stage", "Close date") and capture notes, exported June 1, 2027.' },
    preview: ['# Albany CCTV - capture notes', 'Exported from CRM on June 1, 2027', '| Stage | Proposal |', 'Their budget is probably around 85k, my guess.', '- Send the reference list to Dana by Friday'],
  },
  {
    name: 'Clarification call 2027-06-03.txt', format: 'text', size: 809, pages: 1, units: 12,
    proposal: { type: 'call-transcript', number: null, date: '2027-06-03', confidence: 0.94, by: 'model', evidence: 'A Teams text export: names with time stamps and conversational lines, dated June 3, 2027.' },
    preview: CALL2.slice(0, 5).map((l) => (l.speaker ? `${l.speaker}  ${l.time}  ${l.text}` : l.text)),
    transcript: CALL2,
    speakers: CALL2_SPEAKERS,
  },
];

export const formatOf = (name: string): Format => {
  const n = name.toLowerCase();
  if (n.endsWith('.pdf')) return 'pdf';
  if (n.endsWith('.docx')) return 'word';
  if (n.endsWith('.xlsx') || n.endsWith('.csv')) return 'sheet';
  if (n.endsWith('.json')) return 'json';
  return 'text';
};

export const ACCEPTED = ['.pdf', '.docx', '.xlsx', '.csv', '.json', '.txt', '.md', '.vtt'];
export const isAccepted = (name: string) => ACCEPTED.some((e) => name.toLowerCase().endsWith(e));

/** The stand-in model for a file the user drops: a guess from the file's name, with modest confidence. */
export function guess(name: string, size: number, modelOn: boolean): Sample {
  const n = name.toLowerCase();
  const format = formatOf(name);
  const type: DocType = /q\s*&\s*a|question/.test(n) ? 'qa-addendum'
    : /addend|amend/.test(n) ? 'change-addendum'
    : /call|transcript|meeting|recording/.test(n) ? 'call-transcript'
    : /note|crm|capture/.test(n) ? 'deal-notes'
    : /price|pricing|form|matrix|template/.test(n) ? 'fill-in-template'
    : 'rfp';
  const pages = Math.max(1, Math.round(size / 60_000));
  const number = /(\d+)/.exec(n.replace(/20\d\d/g, ''))?.[1];
  const proposal: Proposal = modelOn
    ? { type, number: typeInfo(type).role === 'change' && number ? Number(number) : null, date: null, confidence: 0.64, by: 'model', evidence: 'Read from the first pages (simulated in this mock).' }
    : { type: /addend|amend/.test(n) ? 'change-addendum' : 'rfp', number: null, date: null, confidence: null, by: 'rules', evidence: 'No model: rules only tell an addendum by its own words; anything else is an RFP.' };
  return {
    name, format, size, pages, units: pages * 14, proposal,
    preview: ['(The mock does not read your file. A real upload shows its first lines here.)'],
    transcript: type === 'call-transcript' ? CALL : undefined,
    speakers: type === 'call-transcript' ? SAMPLE_SPEAKERS : undefined,
  };
}

let counter = 0;
export function newDoc(s: Sample, no: number): Doc {
  counter += 1;
  return {
    id: `doc-${counter}`, no, name: s.name, format: s.format, size: s.size, pages: s.pages, phase: 'uploading', progress: 0,
    error: null, proposal: s.proposal, type: s.proposal.type, number: s.proposal.number, date: s.proposal.date, replaces: null,
    confirmed: false, preview: s.preview, transcript: s.transcript ?? [], speakers: (s.speakers ?? []).map((x) => ({ ...x })),
    speakersConfirmed: false, units: s.units,
  };
}

// --- what is still missing, in the words a bid manager uses ----------------------------------------

export function missing(d: Doc): string[] {
  const t = typeInfo(d.type);
  const out: string[] = [];
  if ((t.role === 'change' || t.role === 'context') && !d.date) out.push('Issue date');
  if (t.role === 'change' && !d.number) out.push('Issue number');
  if (d.type === 'reissued-rfp' && !d.replaces) out.push('Which document it replaces');
  if (t.spoken && d.speakers.length && !d.speakersConfirmed) out.push('Speakers');
  return out;
}

export const ready = (d: Doc) => d.confirmed && missing(d).length === 0;

/** Issue order: base documents first by date, then changes by date and number, then context. */
export function issueOrder(docs: Doc[]): Doc[] {
  const rank = (d: Doc) => ({ base: 0, change: 1, context: 2 })[typeInfo(d.type).role];
  return [...docs].sort((a, b) => rank(a) - rank(b) || (a.date ?? '9999').localeCompare(b.date ?? '9999') || (a.number ?? 0) - (b.number ?? 0) || a.no - b.no);
}

// --- the estimate before anything is spent ---------------------------------------------------------

export function estimate(docs: Doc[], votes: number) {
  const units = docs.reduce((n, d) => n + d.units, 0);
  const calls = docs.reduce((n, d) => n + Math.ceil(d.units / 40) * (votes + 1) + (typeInfo(d.type).role === 'base' ? 2 : Math.ceil(d.units / 60)), 0) + 6;
  const tokens = Math.round(units * (votes + 1) * 420 + calls * 1800);
  const dollars = tokens / 1_000_000 * 1.6;
  const minutes = Math.max(1, Math.round(calls / 45));
  return { units, calls, tokens, dollars, minutes };
}

export const sizeLabel = (b: number) => (b >= 1_000_000 ? `${(b / 1_000_000).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1000))} KB`);

export const SIDE_LABEL: Record<Exclude<Side, ''>, string> = { buyer: 'Buyer', ours: 'Our team', other: 'Other party' };
