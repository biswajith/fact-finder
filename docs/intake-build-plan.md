# Intake redesign: build plan

Build the bid intake of the mock in `web/mock/` into the real web app. The mock is the design: run
`npm run mock` in `web/` (port 5199), click through it, and read its code (`web/mock/App.tsx`,
`web/mock/screens/*.tsx`, `web/mock/mock.css`). Reuse its components and layout as closely as the
real data allows. The mock's data (`data.ts`), fake clock (`store.tsx`) and mock controls are not built.

The real intake today is `web/src/components/bid/*` (one long page) driven by `web/src/bidFlow.ts`
(state, uploads, plan, process job) over `web/src/api.ts`. Keep `bidFlow.ts` as the one source of state
and extend it; replace the screens.

## Decisions already made

- **Light theme only.** The mock has no dark mode, and the user asked for none. Make the app always
  light: `App.tsx` passes `colorScheme="light"`, `theme.tsx` always resolves to light, and the theme
  control in `web/src/components/shell/Sidebar.tsx` is removed. Leave the dark CSS variables in place; they
  are no longer used.
- **What the mock shows that the server cannot give is cut, not faked** (table below). Nothing in the
  real app may show made-up numbers.
- **Two small server additions** (WP1 and WP2) and no others. The extraction pipeline, the playbooks and
  the model calls do not change.
- No new npm or Python dependencies.

## Mock feature → real app

| Mock | Real data | Do |
|---|---|---|
| Bids list (table, search, stage filter) | `GET /api/bids` (`name, documents, facts, run, modified`) | Build. Columns: Bid, Customer, Due, Documents, Stage, Updated. Stage is derived: `Ready` when `run` is set, `Reading` while this bid's job runs (bidFlow knows), else `Intake`. No Owner column. |
| Bid details: name, customer, CRM ID, due date | name and deal_id exist; customer and due do not | Build; add `customer` and `due` on the server (WP1). CRM ID is `deal_id`. |
| Team with roles | team is `[{name}]` | Build; add an optional `role` per member (WP1). |
| Drop zone, Browse | `flow.addFiles` uploads one at a time | Build. Accept the server's types: `.pdf .docx .json .txt .md .csv .xlsx`. |
| Per-file phases: uploading → reading → working out what it is → finding who speaks | one upload request does all of it; `flow.uploads` has `pending` and `error` only | One indeterminate state, "Uploading and reading". After the request, the row comes from the bid. |
| Type with confidence % and "why the model says so" | `proposed.by` (`model`/`rules`) and `proposed.checked` | Show "Suggested by the model" or "Suggested by rules". When `checked` is false, show the existing warning that the number or date was not found in the document. No percentage, no evidence text. |
| "First lines" preview in the panel | none | Cut. |
| Status lights (Ready to confirm, Check: issue date, Confirmed, Could not read) | `status`, `confirmed`, `missing` (server words, see `web/src/bid.ts` `missingWords`), `error` | Build from these. "Could not read" is an upload error (`flow.uploads` error) or a document with `status: failed`. |
| Filters (All, To review, Confirmed, Problems), multi-select with Confirm/Remove action bar, "Accept N suggestions" | per-document PATCH | Build; bulk actions loop over the PATCH/DELETE calls. Hide "Accept N suggestions" when the suggestions came from rules (`proposed.by === 'rules'`). |
| Detail panel sliding over from the right | the document | Build: type picker with description, issue number (change role), issue date, "Replaces" for a reissued RFP, Counts as / Shared outside (from the playbook's `level` and `visibility`), Confirm/Edit/Remove. |
| Speakers page: transcript beside people, colour per speaker, hover highlights lines | speakers are on the document; the lines are not served | Build; add a route for a call's lines (WP2). |
| Side toggles, suggestion and reason, Acts for, Use all suggestions, Confirm speakers | `speakers[].proposed/why/side/acts_for`, PATCH `speakers` + `speakers_confirmed`, `POST .../speakers/suggest` | Build. Keep "Suggest again" (only when the status says an API key is set). A call with "speakers not read yet" in `missing` shows a notice and, with a key, a "Find speakers" button that calls suggest. |
| Several calls as tabs | documents | Build. |
| Reading order timeline | `bid.order`, documents | Build. |
| Accuracy picker, units, model calls | `POST /api/bids/{id}/plan` with `votes` 1, 3 or 5 (`units`, `total_calls`, per document) | Build. |
| Estimated cost, estimated time, budget meter, "email me" | none | Cut. |
| Which document wins (not in the mock) | `PrecedenceOrder`, `bid.precedence` | Keep: put the existing control in the Review step, folded in a Disclosure titled "Which document wins". |
| Start confirmation dialog | `flow` start (POST process, `confirm: true`) | Build. |
| Run progress per document, steps, overall bar | `ExtractJob.steps` (`doc_no`, `step`, `status`), see `stepsByDocument` in `web/src/bid.ts` and `PlanAndStart.tsx` | Build. Overall progress: finished steps over expected steps (4 per document, plus the 3 bid steps). No time-left estimate. |
| Results summary (facts, conflicts, replaced, to check) | after the job the bid has `run`; facts count in `GET /api/bids` | Build with what is real: facts in total and per document (count `facts.json` rows by `doc_no` if the bid view gives it, else total only), and a button "Open the fact list" that opens the bid's run (the existing `selectRun`). Cut the other three numbers. |
| Save draft and close, breadcrumbs, step rail, sticky footer with Back/Next and the blocking reason | navigation only | Build. A bid is created on the server when the user leaves the details step with a name, so a draft is just a bid. |
| Top bar search, notifications, help, side nav items | none | Do not build. The app keeps its own shell (`Workspace.tsx`, `Sidebar.tsx`). |

## Work packages

Do them in order. After each, run the checks listed under Done.

### WP1. Bid fields: customer, due date, team roles (server)

- `src/fact_extractor/bid.py`: `create(root, name, deal_id="", customer="", due=None)`; the manifest gains
  `customer` (string) and `due` (`YYYY-MM-DD` or null). Old manifests without them read as `""`/null.
  A team member is `{name, role}`, role optional (`""`).
- `src/fact_extractor/web/server.py`: `BidIn` and `BidPatch` accept `customer` and `due`; `due` must be
  a real date in `YYYY-MM-DD` or null (400 otherwise, as issue dates are checked). The team PATCH keeps
  `role` (a string, trimmed). `list_bids` and `bid_view` return `customer` and `due`.
- `web/src/types.ts` and `web/src/api.ts`: the new fields.
- Tests in `tests/test_bid.py` and `tests/test_web_bids.py`: create with and without the fields, PATCH
  them, a bad due date is a 400, roles survive a PATCH, an old manifest still loads.

### WP2. A call's lines (server)

- `GET /api/bids/{bid_id}/documents/{no}/lines?limit=400` returns
  `{"lines": [{"id", "text", "speaker"}], "total": n}`: the document's units in order (`bid.read(d)`),
  `speaker` from `d["voices"]` (`""` for a line no one speaks). 400 when the document's playbook is not
  spoken (`playbooks.load(...).spoken`); 404 for an unknown document. Read in a thread
  (`asyncio.to_thread`), as other routes do.
- `api.ts`: `getBidDocumentLines(bid, no, limit?)`.
- Test in `tests/test_web_bids.py`: a call uploaded with the scripted small model (see `small_model` in
  that file) returns its lines with speakers; a deal-notes document is a 400.

### WP3. Shell and bids list

- Light theme only (see Decisions).
- `web/src/components/intake/` holds the new screens; port `mock.css` into `web/src/components/intake/intake.css`
  (class names prefixed `in-` so they do not clash with `pages.css`). Use Spectrum CSS variables only.
- The Documents page (`page === 'documents'`, also the `NoRuns` screen in `App.tsx`) shows the bids
  list when no bid is open, and the wizard for the open bid. "New bid" opens the wizard on its details
  step. The `?bid=` URL parameter keeps working.

### WP4. Wizard: rail, footer, details step

- Step rail and footer as in the mock (`useSteps` in `web/mock/App.tsx` is the model for what is done,
  what is enabled and what blocks Next).
- Details step creates the bid (`createBid` with name, deal ID, customer, due), then PATCHes the team.
  Editing later PATCHes. Customer is a ComboBox over the customers of existing bids, free text allowed.
  The team ComboBox suggests names already used on other bids' teams; items use `<Text>` and
  `<Text slot="description">` (raw mixed text inside an `Item` overlaps).

### WP5. Documents step

- As in `web/mock/screens/DocumentsStep.tsx`, on real data per the table. Keep the upload order and
  the one-at-a-time chain in `bidFlow.ts`.
- The detail panel is the mock's `Inspector`, sliding over from the right, closed by Escape or ×.
- A DropZone `onDrop` gets `FileDropItem`s: `await item.getFile()` gives the `File` to upload.

### WP6. Speakers step

- As in `web/mock/screens/SpeakersStep.tsx`, lines from WP2. Changing a side PATCHes only on
  "Confirm speakers" (keep a local draft per call, as `SpeakersPanel.tsx` does today).
- The real side values are `buyer | ours | other | unknown`; "unknown" shows as no side chosen.

### WP7. Review and run

- Review as in `web/mock/screens/ReviewStep.tsx` without cost, time, budget and email; with the
  precedence Disclosure. Unconfirmed documents and calls without speakers are listed in the notice.
- Run as in `web/mock/screens/RunStep.tsx` on `flow.job`. The job keeps being followed when the user
  leaves the page (bidFlow already does this). On a failed document, show its error and keep the others.
- Delete the old screens that are no longer used (`NewBidScreen`, `DocumentsTable`, `PlanAndStart`,
  `TeamList`, `DropZone`, `SpeakersPanel`) and their CSS in `pages.css`; keep helpers in `bid.ts` that are
  still used, and update `web/src/bid.test.ts` / `bidView.test.ts` for any helper that changes.

## Done

- `uv run pytest -q` passes.
- In `web/`: `node node_modules/.bin/tsc --noEmit -p .` and `node node_modules/.bin/vitest run` pass.
- A walk-through in the browser against the real server (launch config `fact-web` in
  `.claude/launch.json`, runs folder `runs/`; with the Vite dev server `npm run dev` on 5173 proxying
  `/api` to it): create a bid, upload the sample files from `web/mock/public/samples/`, confirm, place the
  speakers of both calls, review, and (only with an API key) extract. Without a key, check every step up
  to Review and say which steps could not be reached.
- No commits: leave the changes in the working tree for review.
