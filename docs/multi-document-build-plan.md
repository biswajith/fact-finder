# Many documents, one bid: build plan

Implements `docs/multi-document-design.html` (the spec). Branch: `feature/multi-document-bid`.
Work packages run one at a time, in order. Each package owns the files it lists; it does not edit
other files except to fix a test or import it broke.

## Rules for every package

- Read the spec section named in your package before coding. Read every file you change in full first.
- Work in `/home/biswa/workspace/fact-extractor` on the branch `feature/multi-document-bid`. Do not
  switch branches, do not push, do not touch `main`.
- Earlier packages are already committed. Use what they built; do not rewrite it. If a contract below
  does not match the code you find, follow the code and say so in your report.
- The model gives closed answers; code checks and applies them. A fact's text is never rewritten by code.
- Prompt text: general rules only. No names, dates, numbers or wording taken from the files in
  `examples/multi-doc/` or the two RFP PDFs in the repo root.
- No real model calls and no network in tests. Use `tests/conftest.py::ScriptedClient` and the
  scripted fakes in `tests/test_web_*.py`.
- Run `uv run pytest -q` before you finish; all tests must pass (392 passed before this work started).
  Web packages also run, from `web/`: `export PATH="$HOME/.local/node/bin:$PATH"; npm run typecheck && npm test && npm run build`.
- Plain code in the style of the file you are in: type hints, short docstrings that say why, no new
  dependencies unless your package names one.
- Finish with one commit on the branch: subject line in the imperative, under 70 characters, a short
  body, ending with the line `Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>`.
- Report back in under 200 words: what was built, files changed, tests added and the pytest result
  line, and every place you departed from this plan and why.

## Shared contracts

### Document properties (spec "Three properties of a document")

| playbook name | authority | form | role | level | visibility | calls |
|---|---|---|---|---|---|---|
| `rfp` | buyer | pdf | base | 1 | external | LABEL STATE CHECK XREF |
| `reissued-rfp` | buyer | pdf | base, aligned | 1 | external | as rfp |
| `change-addendum` | buyer | pdf | change | 1 | external | as rfp + RELATE |
| `qa-addendum` | buyer | pdf | change | 1 | external | as rfp + RELATE |
| `fill-in-template` | buyer | sheet (or pdf) | base | 1 | external | LABEL STATE |
| `call-transcript` | by speaker | transcript | context | 2 buyer / 3 ours | internal | LABEL STATE RELATE |
| `deal-notes` | notes | notes | context | 4 | internal | LABEL STATE RELATE |

Relation kinds: `REPLACES REMOVES ADDS CLARIFIES CONFIRMS DISAGREES NONE`.
Addenda may use `REPLACES REMOVES ADDS CLARIFIES CONFIRMS DISAGREES NONE`; transcripts and notes
`CONFIRMS CLARIFIES DISAGREES ADDS NONE`.

New category codes (multi-letter, only in the transcript and notes playbooks):
`PRIORITY` buyer priority, `DECIDER` who decides or influences, `BUDGET` money the buyer has or expects,
`QUESTION` open question to settle, `COMPETITOR` competitor intelligence (notes only),
`ACTION` something our team must do (notes only). New model flags: `tentative` (transcript, notes),
`precedence` (buyer-document playbooks: the unit states an order of precedence between documents).

### `Playbook` (WP1, `src/fact_extractor/playbooks/__init__.py`)

```python
@dataclass(frozen=True)
class Playbook:
    name: str; description: str; version: int
    cutter: str                      # "pdf" | "transcript" | "notes" | "sheet"
    authority: str                   # "buyer" | "speaker" | "notes"
    role: str                        # "base" | "change" | "context"
    codes: tuple[str, ...]; flags: tuple[str, ...]      # model-voted flags
    precedence: tuple[str, ...]      # tie-break order of codes
    calls: tuple[str, ...]           # subset of LABEL STATE CHECK XREF RELATE
    relations: tuple[str, ...]; relate_to: str          # "" | "buyer documents"
    votes: int; level: str           # "1" | "by speaker" | "4"
    visibility: str                  # "external" | "internal"
    sections: tuple[str, ...]        # summary section keys
    body: str                        # the markdown under the header
    @property
    def key(self) -> str: ...        # f"{name}@{version}"
    def system(self) -> str: ...     # the system prompt for the label round
def load(name: str) -> Playbook
def names() -> list[str]
def all() -> list[Playbook]
```

Playbook files are `src/fact_extractor/playbooks/<name>.md`: a header between `---` lines
(`key: value`, lists as `[a, b]`, `#` comments; parsed by a small parser in the package, no YAML
dependency), then the body.

### `Anchor` and citations (WP2)

`Anchor` gains two fields with defaults, at the end: `speaker: str = ""`, `side: str = ""`
(`"buyer"`, `"ours"`, `"unknown"` or `""`). `Anchor.citation()` adds `"doc_id"`, and `"speaker"` and
`"side"` when set. `runs.normalize` gives every citation `doc_id` (falling back to the fact's `doc_id`),
`doc_no` (int, 0 outside a bid), `speaker`, `side`, `level` (int, 0 unknown) and
`visibility` (`"external"` default). A citation key is the pair `(doc_id, id)`: helper
`runs.cite_key(c) -> tuple[str, str]`.

### Stored result of one document (WP2, `results.py`)

Folder `runs/<doc_id>/<run_id>/` as today, plus:
- `meta.json` gains `playbook` (e.g. `"rfp@1"`), `source_name` (original file name), `source_file`
  (`source.pdf`, `source.json`, `source.md`, `source.txt`, `source.csv`, `source.xlsx`).
  A meta without `playbook` counts as `rfp@1`.
- `units.json`: every unit as `{id, page, page_label, section, text, kind, bbox, speaker, side}` in
  document order. Written for every new result. `results.load_document(folder, doc_id) -> TaggedDocument | None`
  rebuilds the tagged document from it without the source file.
- `relations.json` (WP4), `alignment.json` (WP6).
`ResultStore.find(sha256, pipeline, doc_id, playbook="rfp@1")` and `save(..., playbook="rfp@1",
source_name="source.pdf", units=None)`. `VERSION` stays `units-5`.

### The bid (WP3, `src/fact_extractor/bid.py`)

A bid is the folder `runs/_bids/<bid_id>/`:
- `bid.json`: the manifest (below). Written atomically.
- `files/<no>_<safe file name>`: every uploaded file as uploaded.
- `facts.json`, `report.json`: derived by `build()`, never edited by hand. Because `facts.json` sits two
  levels under `runs/`, the existing web app opens a bid as the run `_bids/<bid_id>`.
- `conflicts.json`: conflicts code raised for documents (WP4/WP5), derived by `build()`.
- `pairs.json`: the pair check's stored answers (WP5).
- `workspace/`: the user's correction log, as for a run.

```json
{"bid_id": "ulster-2026", "name": "Ulster County actuarial", "deal_id": "ulster-2026", "created": "...",
 "team": [{"name": "Tom Okafor"}],
 "precedence": null,
 "documents": [
  {"no": 1, "doc_id": "RFP-UC26-039", "file": "files/1_RFP-UC26-039.pdf", "file_name": "RFP-UC26-039.pdf",
   "sha256": "...", "pages": 31,
   "proposed": {"playbook": "rfp", "issue_number": null, "issue_date": "2026-07-20", "by": "model|rules", "checked": true},
   "playbook": "rfp", "issue_number": null, "issue_date": "2026-07-20", "confirmed": true,
   "previous": null,
   "speakers": [],
   "speakers_confirmed": false,
   "run": "RFP-UC26-039/run_2026_11_22_ab12cd",
   "status": "uploaded|confirmed|extracting|extracted|failed", "error": ""}
 ]}
```
- `no` is the upload sequence number and never changes; a citation shows the document as `d<no>`.
- `precedence`: null, or a list of doc_ids the user confirmed, highest first.
- `speakers`: `[{"id": "<speakerId or name>", "name": "...", "side": "buyer|ours|unknown",
  "proposed": "buyer|ours|unknown", "why": "team list|B fact|Gong affiliation|none"}]`.
- `previous`: for `reissued-rfp`, the doc_id it replaces.

Issue order (`bid.issue_order(manifest) -> list[doc]`): sort by
`(issue_date or "9999-12-31", issue_number or 0, no)`; then, among the documents whose playbook role is
`change`, put them in `(issue_number or 0, issue_date, no)` order inside the positions they already hold
(number wins over date for addenda). Upload order never counts.

Levels: buyer authority → 1. Transcript fact → 2 when any of its units has `side == "buyer"`, else 3; a
fact with units of both sides also gets the flag `both-sides` and shows the source's words (no STATE
statement). Notes → 4. Every fact record in the bid's `facts.json` carries `doc_no`, `level`,
`playbook`, and its citations carry `doc_id`, `doc_no`, `level`, `visibility`.

### Relations (WP4, `src/fact_extractor/relate.py`)

`relations.json` of a document: `{"playbook": "...", "against": [doc_ids], "units": [{"unit": "p1.4",
"kind": "REPLACES", "targets": [{"doc_id": "RFP", "unit": "p2.31"}], "candidates": [...same shape...],
"votes": ["REPLACES"]}], "incomplete": ["p3.2"], "held_refs": [...]}`. One row per unit of the document.
Inside the RELATE prompt a unit of another document is written `d<no>:<unit id>`; code maps the token
back before storing.

### Fact fields added in the bid's facts.json

`doc_no`, `level`, `playbook`, `relations` (list of `{"id": "r_<10 hex>", "kind", "from": {doc_id, unit,
fact_id}, "to": {doc_id, unit, fact_id}, "rejected": false}` — on both ends), `replaced_by`
(fact_id or `""`), `stale` (`""` or `"section partly replaced"`), flags may gain `replaced`,
`both-sides`, `tentative`, `precedence`.

### Conflicts raised for a document

Same shape as a raised conflict, `kind: "document"`, fixed ID `d:<10 hex of sha1 of the sorted fact IDs
and a reason word>`, plus `"reason"` (`"user-edited fact replaced" | "old value elsewhere" | "depends on
changed value" | "levels disagree" | "unfound target"`), and `"closed_by"` (doc_id) when a later buyer
document settled it. Options carry `changes` like today's raised conflicts; one option may be
`{"label": "Ask the buyer", "question": true, "changes": []}`.

### Web API added (WP7), all under `/api`

| Route | Body → answer |
|---|---|
| `GET /bids` | list of `{bid_id, name, run, documents, facts, modified}` |
| `POST /bids` | `{name, deal_id?}` → manifest |
| `GET /bids/{bid}` | manifest, with `order` (doc_ids in issue order) and `playbooks` (name, description, role, form) |
| `PATCH /bids/{bid}` | `{name?, team?, precedence?}` → manifest |
| `POST /bids/{bid}/documents?name=` | raw file body → the new document entry (uploaded, CLASSIFY proposed) |
| `PATCH /bids/{bid}/documents/{no}` | `{doc_id?, playbook?, issue_number?, issue_date?, previous?, confirmed?, speakers?, speakers_confirmed?}` → entry |
| `DELETE /bids/{bid}/documents/{no}` | → `{ok}` (only before it is extracted) |
| `POST /bids/{bid}/plan` | → per confirmed, unextracted document: planned calls, units, stored result if any |
| `POST /bids/{bid}/process` | `{confirm: true, votes?, model?}` → `{job_id}`; steps reported by `GET /extract/{job_id}` as `steps: [{doc_no, step, status, detail}]` |
| `POST /relations/{rid}/reject?run=` , `.../restore` | → `{ok}` |
| `POST /groups/{gid}/ungroup?run=` , `.../regroup` | → `{ok}` |
| `GET /facts.csv?run=&audience=external` | internal citations left out; a fact with none left is left out |
| `GET /page?run=&page=&fact_id=&doc=` | renders the page of document `doc` (doc_id) of a bid |

## Work packages

### WP1. Playbooks, no behaviour change (spec: Playbooks; Build order 1)

Owns: new `src/fact_extractor/playbooks/` (`__init__.py` and seven `.md` files), `units.py`,
`models.py`, `prompts.py` (only if needed), new `tests/test_playbooks.py`, `pyproject.toml` (ship the
`.md` files in the wheel).

1. Before touching `units.py`, write `tests/fixtures/prompt_snapshot.json` from the current code with a
   throwaway script: `units.SYSTEM`, `units.label_task(["p1.1","p1.2"])`, `units.state_task(["p1.1","p1.2"])`,
   `units.CHECK_TASK`, `units.GROUP_SYSTEM`, `xref.TASK`, and `units.brief_system(sec)` for every section.
2. Write the package with the `Playbook` dataclass, the header parser and `load/names/all` as in the
   contract. Unknown header keys, an unknown cutter, call or relation kind raise `ValueError` naming the file.
3. `rfp.md`: header as in the contract table (`codes: [B, C, G, X, D, S, E, R]`,
   `flags: [post-award, risk, unclear]`, `precedence: [X, G, D, S, E, C, R, B]`, `votes: 3`, `version: 1`,
   sections = the keys of `units.SECTIONS`). `Playbook.system()` for `rfp` must return a string
   byte-identical to today's `units.SYSTEM`. Do this by moving the text of `units.SYSTEM` into the
   playbook: the body holds the reading rules; the category definitions and flag tests still come from
   `prompts.DEFINITIONS` and `prompts.FLAG_TESTS`, inserted where a `{categories}` and a `{flag_tests}`
   line stand in the body. `units.SYSTEM = load("rfp").system()` stays as a module constant, and
   `CODES`, `MODEL_FLAGS`, `PRECEDENCE` stay as module constants read from the rfp playbook.
   Do not add the `precedence` flag to `rfp.md` in this package (it would change the prompt).
4. The other six playbooks, each a complete header and a body of general reading rules written for
   that kind of document (60 to 120 lines of body each is too much; aim for 15 to 35 lines):
   - `reissued-rfp`: same codes, flags and reading rules as rfp; description says a full RFP issued again.
   - `change-addendum`, `qa-addendum`: rfp codes; flags add `precedence`; calls add RELATE;
     relations per the contract; body explains what a point is in an addendum (a change instruction
     such as "Section X is replaced with" states the point of the change; restated unchanged text is
     still a point; in a Q&A the answer states the point, the question is its context; "no change"
     states no point), and that a section with subsections is named by each of its headings.
   - `fill-in-template`: cutter sheet; codes `[S, R, C, D, E, B]`; calls `[LABEL, STATE]`; body: a row
     or field the bidder must fill is S (a thing to submit) or R (a requirement to answer); a value the
     buyer already filled in is a fact of its category; an instruction on the sheet is a fact; an
     empty label or a column header alone states no point.
   - `call-transcript`: exactly the header in the spec's Playbooks section plus `S` and `B` in codes
     and `authority: speaker`; body: the three rules in the spec plus: small talk, greetings and
     scheduling of the call itself state no point; speech-recognition slips are read for what was
     meant but numbers are never corrected; who said it does not change the label.
   - `deal-notes`: cutter notes; codes `[B, D, C, R, E, S, PRIORITY, DECIDER, BUDGET, COMPETITOR, ACTION, QUESTION]`;
     flags `[risk, unclear, tentative]`; calls `[LABEL, STATE, RELATE]`; level 4; visibility internal;
     body: a CRM field row with a value is a point; our own guesses and estimates are points flagged
     tentative; a to-do is ACTION; a heading alone states no point.
   For playbooks with new codes, `system()` builds the CATEGORIES block from `prompts.DEFINITIONS` for
   codes it has and from a `DEFINITIONS` dict you add in `playbooks/__init__.py` for the six new codes
   (one line each, same style: `CODE: name. What it covers.`), and the FLAGS block the same way
   (`tentative`, `precedence` tests added there). The opening line says what is being read
   ("You read a call transcript for a bid manager, unit by unit." etc.) and the INPUT paragraph says
   the same; only `rfp` and `reissued-rfp` keep the exact RFP wording.
5. Thread a playbook through `units.py` without changing behaviour for rfp: add `pb: Playbook | None = None`
   (None means rfp) to `label_task`, `state_task`, `parse_labels`, `vote`, `_rank`, `group`, `modal_flags`
   callers, `to_records`, `_Run.__init__` (cache key uses `pb.system()`), `_Run.call` default system, and
   `extract(..., playbook: Playbook | None = None)`. In `extract`: CHECK runs only when `"CHECK" in pb.calls`
   and `cfg.check`; XREF likewise; STATE likewise; GROUP and BRIEF as today but BRIEF only for sections in
   `pb.sections`; `by_code` uses `pb.codes`; `cfg.votes` is used as given. `state_task` wording
   ("the RFP") stays byte-identical for rfp and says "the document" for other playbooks. `_LEAKED_LABEL`
   stays as is. The report gains `"playbook": pb.key`. Every fact record gains `"playbook": pb.name`.
6. `models.CATEGORIES` gains the six new codes; `models.FLAGS` gains `tentative`, `precedence`, `both-sides`.
7. Tests: the snapshot test (every string in the fixture equals what the refactored code gives);
   every playbook loads; bad headers raise; `parse_labels` accepts `PRIORITY` with the transcript playbook
   and rejects it with rfp; an `extract` run with `ScriptedClient` and the transcript playbook makes no
   CHECK and no XREF call and labels a unit `QUESTION`.

### WP2. Cutters, speakers on units, citations with a document, stored units (spec: Three properties; Who is speaking; Build order 2 and 8 in part)

Owns: new `src/fact_extractor/cutters.py`, `api.py`, `models.py` (Anchor only), `results.py`,
`web/runs.py` (`normalize`, `load_run`, `tag_pdf`, `run_extraction`, `cite_key`, `document_order`),
`web/workspace.py` (`document()` only), `units.py` (`_mark_conflicts`, labels rows), `cli.py` (store call),
tests: new `tests/test_cutters.py`, updates to `tests/test_api.py`, `test_web_runs.py`, `test_units.py`.
New dependency allowed: `openpyxl` (try `uv add openpyxl`; if it cannot be installed, read `.csv` only and
raise `ValueError("xlsx needs openpyxl")` for `.xlsx`).

1. `Anchor`, `citation()`, `normalize`, `cite_key` as in the contract. `api.SourceUnit` gains
   `speaker: str = ""`, `side: str = ""`; `document_from_units` copies them onto the Anchor.
2. `cutters.py`, each returning `list[SourceUnit]` (keys unique, in reading order):
   - `cut_transcript(data: bytes, name: str) -> tuple[list[SourceUnit], dict]`. Two inputs:
     a Gong export JSON (read `examples/multi-doc/KEY.md`, section "The Gong shape", and one of the
     `.gong.json` files for the exact shape: join `transcript.callTranscripts[0].transcript[*].speakerId`
     to `extensive.calls[0].parties`); and plain text with lines `[hh:mm:ss] Name: text` after a header
     block (see the `.txt` files). One monologue or line is one turn; a turn is a "page" (`page` = turn
     number, `page_label` = `hh:mm:ss` of its start); each sentence of the turn is one unit (use
     `tagging.split_sentences`); `section` = the Gong `topic` or `""`; `speaker` = the party's name,
     or its phone number, or `"Speaker <speakerId>"`. The dict returned is call info: `{"title", "date"
     (YYYY-MM-DD), "speakers": [{"id", "name", "email", "title", "affiliation"}]}`.
   - `cut_notes(text: str) -> list[SourceUnit]`: markdown or plain notes. A `#` heading is a heading
     unit and sets `section`; a list item is one `list_item` unit (not split into sentences); a table
     row is one `table_row` unit as `header: value | header: value` (use `tagging.table_row_text`, skip
     the separator row and the header row); a paragraph is split into sentence units. Every `##`
     section starts a new page (`page_label` = the section's number as a string).
   - `cut_sheet(data: bytes, name: str) -> list[SourceUnit]`: `.csv` (csv module) and `.xlsx` (openpyxl,
     `data_only=True`). One sheet is one page (`page_label` = sheet name, `"1"` for csv). The first
     non-empty row of a sheet is its header. Each later row with any non-blank cell is one `table_row`
     unit, `header: value` pairs joined by ` | `, blank cells left out. A row with exactly one non-blank
     cell is a `sentence` unit (an instruction or a title).
   - `cut(form: str, data: bytes, name: str)` dispatches; `form_of(name: str, data: bytes) -> str`
     guesses `pdf | transcript | notes | sheet` from the extension and, for `.json` and `.txt`, the content.
3. `results.py` as in the contract: `playbook` in the key, `source_name`/`source_file`, `units.json`,
   `load_document`. `pdf_hash` gets the alias `content_hash` (keep `pdf_hash`). `runs.load_run` finds
   the source as today for PDFs (`Run.pdf` stays None for other forms) and adds `Run.source: Path | None`.
4. `Workspace.document()`: use `results.load_document` when `units.json` exists, else today's PDF path.
5. `units._mark_conflicts` compares `(doc_id, id)` pairs. `document_order` stays page order inside one
   document (the bid order comes in WP3).
6. `runs.run_extraction` and `cli._extract` pass `playbook="rfp@1"`, `source_name` and the units to `save`.
7. Tests: both transcript inputs give the same speakers and the same number of turns for the Ulster
   example files (test only shape and counts, not wording); notes and sheet cutters on small inline
   fixtures; a stored result round-trips through `load_document`; `find` does not return an rfp result
   for another playbook; a legacy meta without `playbook` is found as `rfp@1`.

### WP3. The bid, CLASSIFY, levels, the bid's fact list (spec: Three properties; Priority ladder; Who does what 1-7; Build order 2 and 4 in part)

Owns: new `src/fact_extractor/bid.py`, new `src/fact_extractor/classify.py`, `web/runs.py`
(`document_order`, `id_position` callers, `find_runs`, `load_run`), `cli.py` (new `bid` subcommand),
new `tests/test_bid.py`, `tests/test_classify.py`.

1. `bid.py` (no FastAPI import, no model import at module level):
   - `Bid(root, bid_id)` with `folder`, `manifest()`, `save(manifest)` (atomic), a lock.
   - `create(root, name, deal_id="") -> Bid`: bid_id = safe, lower-case slug of the name, made unique.
   - `add_document(data: bytes, file_name: str) -> dict`: stores the file, sets `no`, `sha256`, `pages`
     (PDF page count, else 0), a unique `doc_id` (file stem; `-2`, `-3` appended when another document
     of the bid has it), `proposed` from `classify.by_rules`, status `uploaded`. The same sha256 twice
     in one bid raises `ValueError("this file is already in the bid")`.
   - `update_document(no, **fields)`: validates playbook name, `issue_date` as YYYY-MM-DD or null,
     `issue_number` int or null, `doc_id` unique; an extracted document cannot change playbook or doc_id.
   - `remove_document(no)`: only when not extracted.
   - `issue_order(manifest)`, `doc_numbers(manifest) -> dict[doc_id, no]`.
   - `propose_speakers(info: dict, team: list[dict], b_fact_texts: list[str]) -> list[dict]`: exact
     name match against the team list → `ours` (`why: "team list"`); name found in a B fact text →
     `buyer` (`"B fact"`); Gong affiliation `Internal` → `ours`, `External` → `buyer`
     (`"Gong affiliation"`); else `unknown`. Team list wins over B fact, which wins over affiliation.
   - `ready(doc) -> list[str]`: what is still missing before the document may be extracted:
     `"type not confirmed"`, `"issue date missing"` (change and context documents need one),
     `"issue number missing"` (change documents), `"speakers not confirmed"`, `"a speaker has no side"`,
     `"previous version not chosen"` (reissued-rfp).
   - `async extract_document(bid, no, client, *, votes=None, store, on_step=None) -> Stored`: cut with
     the playbook's cutter (`runs.tag_pdf` for pdf), set each unit's `side` from the confirmed speaker
     map, run `units.extract` with the playbook (votes default to the playbook's), then set on every
     record `level` and flags per the contract (both-sides facts: text = source text, `text_from = "rfp"`),
     save through `ResultStore` under the playbook key, and record `run` and status in the manifest.
     A stored result for the same content, playbook and doc_id is reused without a model call.
   - `build(bid) -> list[dict]`: load each extracted document's facts in issue order; add `doc_no`,
     `level`, `playbook`, and on every citation `doc_id`, `doc_no`, `level`, `visibility`; empty
     `relations: []`, `replaced_by: ""`, `stale: ""`; write the bid's `facts.json` and a `report.json`
     (`{"bid_id", "documents": [{doc_no, doc_id, playbook, run, facts}], "facts", "pages": <of the first
     base document>, "doc_id": <bid_id>, "run_id": "bid", "summaries": <of the first base document>}`).
     Later packages add steps to `build`; keep it a list of small functions applied in order.
2. `classify.py`:
   - `by_rules(file_name, data) -> dict`: form from `cutters.form_of`; pdf → `change-addendum` when the
     first page's text has "addendum" or "amendment" as a word, `qa-addendum` when it also has
     "questions and answers" or "q&a", else `rfp`; transcript → `call-transcript`; notes → `deal-notes`;
     sheet → `fill-in-template`. Issue number: the first `addendum (no.|number|#)? N` on the first page.
     Date: the first date `normalize.values` reads on the first page (Gong `started` for a transcript,
     an "Exported ... YYYY-MM-DD" style date for notes when there is one). `by: "rules"`.
   - `async by_model(file_name, first_text, client) -> dict | None`: the CLASSIFY call. System prompt:
     each playbook's `name: description`; user: the first 3000 words of the document's units. Answer
     format, one line: `PLAYBOOK|issue number or -|date as YYYY-MM-DD or -`. Code keeps the playbook
     only if it exists, the number only if it is on the pages read, the date only if `normalize.values`
     finds that date in the text read; a field that fails keeps the rules' value and sets
     `checked: false`. Returns None when the call fails. Uses `llm.Request` and the client as
     `units._Run.call` does (one retry).
3. `runs.document_order`: by `(position of the fact's doc_no in the order found on the records, page,
   id_position)`; records without `doc_no` behave as today. `find_runs` also lists bids (the glob
   already matches `_bids/<bid_id>/facts.json`); `RunRef` gains `kind: "bid" | "document"` and
   `documents: int`. `load_run` for a bid: `pdf=None`, `doc_id` = bid_id.
4. CLI: `fact-extractor bid create NAME`, `bid add BID FILE... [--type PLAYBOOK] [--number N] [--date D]
   [--yes]` (prints the proposal; `--yes` confirms it), `bid speakers BID NO NAME=side...`,
   `bid run BID [--votes N] [--model M]` (extracts every ready document, then `build`), `bid show BID`.
5. Tests with `ScriptedClient`: create, add (unique doc IDs, duplicate refused), issue order (an
   addendum uploaded first still sorts after the RFP; addendum 3 dated before addendum 2 still applies
   after it), speaker proposal precedence, `ready`, `extract_document` for a notes file and a transcript
   (levels 4, 2, 3 and `both-sides`), `build` output fields, `by_rules` on small made-up inputs,
   `by_model` keeping and dropping fields.

### WP4. RELATE, relations under the correction log, document conflicts (spec: Addenda; When sources disagree; Changes to the correction log; Build order 3, 4, 6)

Owns: new `src/fact_extractor/relate.py`, new `src/fact_extractor/ladder.py`, `bid.py` (`build`
steps and `extract_document` hook), `xref.py`/`units.py` (hold-back only), `web/workspace.py`,
new `tests/test_relate.py`, `tests/test_ladder.py`, updates to `tests/test_web_workspace.py`.

1. `relate.py`:
   - `candidates(doc, records, earlier: list[tuple[int, TaggedDocument, list[dict]]], refs) -> dict[unit_id, list[tuple[doc_no, unit_id]]]`.
     For a unit XREF found a section reference in: the headings of the earlier documents (role-matching:
     buyer documents only). For any unit: units of earlier facts that share a `normalize.values` token
     with it, plus the top 8 earlier facts by word overlap (`normalize.words`, rare words weighted: reuse
     the ranking idea in `web/agent.py::_search_one` but do not import the web package; a small function
     here is fine). At most 12 candidates a unit; at most 40 headings.
   - `SYSTEM`/`relate_task(batch)`: the prompt. Each unit line `[d2:p1.4] text`, then its candidates
     indented as `  > [d1:p2.31] text` (headings marked `(heading)`). Explain each kind in one line
     (take the meanings from the spec table "Addendum says | RELATE | Code does"), that a heading
     stands for the units from it to the next heading, that a section with subsections is named by
     listing each heading, and that targets must be IDs shown as candidates. Answer one line per unit:
     `ID|KIND|target IDs comma-separated or empty`, then `END|n`. Only the playbook's kinds are offered.
   - `parse(text, batch, allowed_kinds) -> dict[unit, (kind, targets)]`: drops a line whose kind is not
     allowed or whose targets were not candidates of that unit.
   - `async relate(doc, doc_no, pb, records, earlier, client, cfg) -> dict`: batches of 30 units, one
     call each (system = `relate.SYSTEM`, no document prefix), asks once more for units left out,
     records the rest in `incomplete`; returns the `relations.json` content. Called from
     `bid.extract_document` after the label round when `"RELATE" in pb.calls`, with the earlier
     documents by issue order whose authority is buyer; the result is saved as `relations.json`.
   - Hold-back: on a document whose playbook has RELATE, an XREF problem about a section reference
     with no target in its own document is not written as a Q fact; it is kept in `held_refs`. After
     RELATE, a held reference whose unit got kind `NONE` or no target becomes a Q fact
     ("refers to <reference>, which was not found in the earlier documents") added to that document's
     facts. Add a parameter to `units.extract` (`hold_section_refs: bool = False`) and return the held
     ones on `RunResult.held_refs`.
2. `ladder.py` (pure, no model):
   - `outcome(new_level, old_level, later: bool, precedence_says_old: bool) -> str`: one of
     `"replace"` (both level 1 and the new one is later, or precedence says the new one governs),
     `"keep-old"` (both level 1 and precedence says the old one governs), `"conflict"` (new is level 2
     to 4 and they disagree: both kept, the user decides), `"q-fact"` (both level 1 issued together:
     same issue date and number).
   - `apply(docs_in_order, facts_by_doc, relations_by_doc, rejected: set[str], precedence) -> Applied`
     where `Applied` holds the facts (with `relations`, `replaced_by`, flag `replaced`, `stale`) and
     the list of document conflicts to raise. Rules: REPLACES/REMOVES/DISAGREES from a level-1 document
     against a level-1 fact follow `outcome`; a heading target reaches every fact whose main unit lies
     from that heading to the next heading of that document; a relation target that is a unit of no
     fact marks nothing but is stored; CONFIRMS/CLARIFIES/ADDS/NONE mark nothing. DISAGREES from level
     2 to 4 → a document conflict (`"levels disagree"`) whose options are: keep the buyer document's
     fact (no changes), rely on the lower source (changes: mark the buyer fact `replaced`), ask the
     buyer (`question: true`). When some units of a section are replaced but not its heading, the
     section's other current facts get `stale = "section partly replaced"`. A rejected relation ID is
     skipped everywhere. Relation ID: `"r_" + sha1(from doc|from unit|kind|to doc|to unit)[:10]`.
3. `bid.build` gains: load each document's `relations.json`, call `ladder.apply`, write `conflicts.json`.
   It reads the bid's correction log only for two things: the rejected relation IDs, and which facts
   the user edited (a replaced fact the user had edited is not flagged replaced; a conflict
   `"user-edited fact replaced"` is raised with options "use the new document's fact (mark mine
   replaced)" and "keep my edit").
4. `web/workspace.py`: `_entry` accepts source `"document"`. New log ops and methods:
   `reject_relation(rid, source="ui")`, `restore_relation(rid)` (op `reject_relation`, undone by undo),
   `ungroup(gid)`, `regroup(gid)` (op `ungroup`). `replay(base, log, doc=None, derived=None)`: `derived`
   is the content of `conflicts.json`; each becomes a conflict of kind `"document"` with its fixed ID,
   resolvable like a raised conflict (changes of the chosen option are logged as edits with that
   `conflict_id`, exactly as `resolve` does for raised conflicts today; read `resolve` first). A derived
   conflict with `closed_by` shows as resolved with the label "Settled by <doc_id>" unless the user had
   already resolved it, in which case it is shown open again with a note "A later document changes
   this". `ungroup` clears `group_id/kind/title` on the group's facts in replay. A workspace on a bid
   folder rebuilds the bid (`bid.build`) after `reject_relation`/`restore_relation`. `Workspace.document()`
   for a bid returns None; user-added facts in a bid accept citation IDs written `d<no>:<unit>` and
   resolve them against that document's stored units.
5. Tests: `parse` drops bad lines; candidates include a shared-date fact and a heading; the spec's two
   worked examples as fixtures built by hand (due date changed: base fact replaced, relation on both
   ends; section replaced by heading: every fact in the section replaced); addendum 3 loaded before 2
   applies after it; a level-2 DISAGREES raises a conflict and replaces nothing; a rejected relation is
   not applied and undo restores it; user-edited fact → conflict; `closed_by`; held reference → Q fact.

### WP5. GROUP across the bid, the pair check, review band (spec: Duplicates across documents; Addenda step 4; Build order 5)

Owns: new `src/fact_extractor/bidgroup.py`, `bid.py` (`build` steps, a `settle` coroutine),
`units.py` (`group_task`, `apply_groups` signature only), `web/runs.py` (`items`), new `tests/test_bidgroup.py`.

1. `units.group_task(code, facts, doc_labels=None)`: when `doc_labels` is given each line names its
   document (`3. [d2 p.4] text`); unchanged otherwise. `apply_groups(records, groups, doc_id)` keeps
   its behaviour; the bid passes the bid_id so group IDs hash the bid.
2. `bidgroup.py`:
   - `async group_bid(facts, bid_id, client, cfg) -> report`: per category with 4 or more current
     facts from 2 or more documents, one GROUP call over the bid's facts of that category (replaced
     facts included, so a restated rule groups with the one it replaced); `apply_groups` with the bid_id.
     Per-document groups are dropped first (the bid's groups replace them).
   - `pairs(facts) -> list[dict]`: (a) two facts from different documents in one group that
     `apply_groups` turned into "Related statements" because their values differ; (b) for every
     replaced fact, other current facts in any category that hold a `normalize.values` token the
     replaced fact had and its replacement does not (`reason: "old value"`); (c) for every replaced
     fact, the top 8 current facts by the word-overlap ranking that hold no value token at all
     (`reason: "depends"`, asked the second question). Each pair has a stable `id` (sha1 of the two
     fact IDs and the reason) and is listed once.
   - `async check_pairs(pairs, facts, checker, stored) -> dict`: asks `ConsistencyChecker._ask`
     (import it lazily; pass the checker in) for pairs not in `stored` (`pairs.json`), in batches by
     "new" fact; for `depends` pairs it uses a second instruction text, added here: "Does the existing
     fact set a date, amount or rule by reference to the value the new fact changes?". Stores
     `{pair_id: {"probability", "at", "skipped"}}`. A failed or keyless check records `skipped` and is
     run again next time.
   - `settle(pairs, answers, facts, order, precedence, threshold=0.7, review=0.5) -> list[conflict]`:
     at or above the threshold the ladder decides: both level 1 → the earlier fact gets a document
     conflict `"old value elsewhere"` whose first option carries the edit of its text to the later
     value when exactly one value token differs (`changes: [{"op": "edit", ...}]`, label
     "Update to <new value>"), else an option that marks it replaced; a `depends` pair → conflict
     `"depends on changed value"` with options "Still correct" and "Mark for review" (adds flag
     `unclear`); levels differ → `"levels disagree"` as in WP4. Between `review` and the threshold the
     later fact gets `stale = "may conflict with <fact id>"` and nothing else. `REVIEW_BAND = 0.5` is a
     module constant with a comment that it is unmeasured.
3. `runs.items`: a "same" group shows its highest current member first: order members by
   (not replaced, lowest level number, latest document in issue order). `Item.first` is then the
   governing fact; a group whose current members are all replaced shows as plain facts.
4. `bid.build` stays pure (no model): it applies stored groups (`groups.json`) and stored pair answers.
   New `async bid.settle(bid, client, checker)` runs `group_bid` and `check_pairs`, stores their
   output, then calls `build`. `bid run` and the process job (WP7) call it after extraction.
5. Tests: the font-rule example (restated rule: one "same" group, shown under the addendum's fact);
   the due-date example from the spec (replaced D fact; X and S facts with the old date become
   conflicts offering the edit; the site visit pair answered 0.1 is untouched; the relative-date fact
   comes through `depends`); review band; skipped check recorded and retried; group IDs differ between
   two bids with the same facts.

### WP6. Reissued RFPs (spec: Reissued full RFPs; Build order 7)

Owns: new `src/fact_extractor/reissue.py`, `bid.py` (the reissue branch of `extract_document`, a
`build` step), `web/workspace.py` (fact ID map in replay), new `tests/test_reissue.py`.

1. `reissue.align(old: TaggedDocument, new: TaggedDocument) -> dict[new_unit, old_unit]`:
   `difflib.SequenceMatcher` over the units' normalised text (`xref.norm`-style: lower case, collapsed
   spaces), `autojunk=False`; equal blocks pair in order. Kinds must match.
2. `async reissue.extract(new_doc, old_stored, client, pb, cfg) -> RunResult`: aligned units keep the
   old votes and label (from the old `labels.json`); unaligned units, and any continuation whose coded
   unit is unaligned, are labelled and stated by the model in the usual batches (pass only those IDs
   to LABEL and STATE; add an `only: list[str] | None` parameter to `units.extract` for this and a
   `carried: dict[unit, Voted]` one). CHECK and XREF run on the whole new document. A fact is carried
   when every one of its units aligns to the units of one old fact; `alignment.json` stores
   `{"previous": doc_id, "units": {new: old}, "facts": {old_fact_id: new_fact_id}, "changed": [...],
   "new": [...], "removed": [old unit ids]}`. A carried fact keeps the old statement.
3. `bid.build`: facts of the previous version leave the current list: carried ones are dropped (their
   counterpart continues), the rest stay with flag `replaced` and `replaced_by: ""`, `stale: "not in
   the reissued RFP"`. The report lists changed, new and removed counts.
4. `Workspace` replay on a bid: before replaying, map every log entry's `fact_id` (and the fact IDs in
   `raise` fields and conflict changes) through the bid's merged old→new map, so corrections follow
   the carried fact.
5. Tests: alignment with a repeated sentence pairs in sequence; a changed sentence is labelled again
   and its neighbours are not (count the IDs in the scripted LABEL requests); a user edit on an old
   fact shows on the new fact after the reissue; removed facts are flagged.

### WP7. Web API for bids (spec: Who does what; Build order 2 to 4 for the web)

Owns: `web/server.py`, `web/runs.py` (CSV, plan, page), new `tests/test_web_bids.py`.
Routes exactly as in the contract table. Details:
1. Uploads: `read_body` limit stays. Accepted extensions: `.pdf .json .txt .md .csv .xlsx`; anything
   else is a 400 "this file type is not supported". After `add_document`, when an API key is set (or a
   classifier is injected through `create_app(classifier=...)`), run `classify.by_model` and store the
   result as `proposed` (`by: "model"`); otherwise the rules' proposal stands. For a transcript, fill
   `speakers` with `bid.propose_speakers` at upload and again whenever the team list changes while
   `speakers_confirmed` is false.
2. `POST /bids/{bid}/plan`: for each document that is confirmed and not extracted: `ready` problems,
   units, `plan_rows`-style rows honouring the playbook's calls and votes (add RELATE rows: one per 30
   units), and the stored result if one exists. Total calls across the bid.
3. `POST /bids/{bid}/process`: one job at a time (shared with `/extract`). The worker thread runs, in
   issue order, `extract_document` for each ready document, then `bid.settle`, then `build`; steps
   (`cut`, `label`, `relate`, `group`, `pairs`, `build`) are appended to the job as they start and
   finish. A document that fails is marked failed with its error and the rest continue; the job ends
   `done` with `run: "_bids/<bid_id>"` when at least one document is extracted. `create_app` gains
   `bid_client=None` (an `LLMClient` for tests) and reuses `checker`.
4. `GET /runs` rows gain `kind`, `name`, `documents`. `GET /facts` for a bid adds
   `documents: [{no, doc_id, file_name, playbook, level, visibility, issue_date, issue_number, has_pdf}]`
   in issue order. `/facts/list` gains filters `docs` (comma-separated doc numbers) and `levels`.
5. `/page` with `doc`; without it, the document of the fact's first citation on that page.
6. CSV: columns gain `document`, `level`, `visibility`; `audience=external` filters as in the contract.
7. Relation and group routes call the Workspace methods of WP4 and return the changed state.
8. Tests: the whole flow through the ASGI client with scripted models: create a bid, upload a small
   PDF made with pymupdf, a notes file and a Gong JSON built inline, confirm, set the team, confirm
   speakers, plan, process, read facts with levels and doc numbers, external CSV has no internal
   citation, reject a relation, unsupported file type, duplicate file, process refused while a
   document is not ready (the answer lists what is missing).

### WP8. Web UI: upload flow and bid documents (spec: picture 1; Who does what 1-5)

Owns: `web/src/components/NewRunTab.tsx` (replaced by the bid flow), `web/src/newRun.ts`, new
`web/src/components/bid/*.tsx`, `web/src/bid.ts`, `web/src/api.ts`, `web/src/types.ts`, `web/src/nav.ts`,
`web/src/components/shell/Sidebar.tsx`, `web/src/App.tsx`, `web/src/components/pages.css`, tests
`web/src/bid.test.ts`.

The page is named "Documents" (hash `#/new` stays valid and opens it; add `#/documents`). It lives
in the Review group of the sidebar, above Overview. Layout, top to bottom:
1. Bid header: a picker of bids and "New bid" (name field, Create). With no bid, only this shows.
   The sidebar's run selector lists bids first ("<name> · N documents"), then single-document runs.
2. Drop zone "Add documents": multiple files, drag and drop or choose; accepts
   `.pdf .json .txt .md .csv .xlsx`; says which kinds of document those are. Each file uploads on its own
   with a row showing progress or its error.
3. Documents table, in issue order, one row a document: `d<no>`, file name, type (a Picker of
   playbooks with the proposal preselected and a "suggested" mark while unconfirmed), issue number
   (number field, shown for addenda), issue date (date field), level and visibility (read-only chips
   derived from the type: "Level 1 · buyer document", "Internal"), status chip, and actions
   Confirm / Edit / Remove. A proposal field that failed code's check (`checked: false`) shows
   "not found in the document; check it". For `reissued-rfp` a picker "Replaces" lists the bid's RFPs.
   Under the table: "Issue order decides which document wins, not upload order."
4. Speakers panel for each transcript, opened by its row: one line per speaker with name (editable
   when it is a phone number or "Speaker N"), why the side was proposed, and a Buyer / Our side radio;
   "Confirm speakers" is disabled until every speaker has a side.
5. Team list editor (names, one per line) with the note that names are matched exactly.
6. Order of precedence: shown when any fact carries the `precedence` flag or on demand: the buyer
   documents as a list the user reorders with up/down buttons, "Confirm order" and "Clear (later
   issue wins)".
7. Planned calls (from `/bids/{bid}/plan`) per document, folded as today's table is; what is still
   missing per document in plain words; the token-spend confirmation checkbox; "Extract N documents";
   while the job runs, a step list per document (cut, label, relate, group, pairs, build) with the
   current one marked; on done, the bid opens on Overview.
Keep the look of today's page (`pg-*` classes, React Spectrum controls). `bid.ts` holds the pure
helpers (level and visibility of a playbook, what is missing, order of rows) with vitest tests.

### WP9. Web UI: documents, levels and relations on facts and conflicts (spec: Duplicates; Addenda; Priority ladder)

Owns: `web/src/components/FactsTab.tsx`, `FactDetail.tsx`, `CitationChip.tsx`, `ConflictCard.tsx`,
`ConflictsTab.tsx`, `facts/parts.tsx`, `facts.css`, `factsQuery.ts`, `types.ts`, `api.ts`, `OverviewTab.tsx`
(counts only), `WEB_UI_SPEC.md`, `README.md`, tests `factsQuery.test.ts`.
1. Types: new category codes with names, new flags, the fact and citation fields of the contract,
   conflict kind `document` with `reason`, `closed_by`, option `question`.
2. A citation chip in a bid reads `d2 · p.4` with the document's file name in its tooltip; internal
   citations carry an "Internal" mark; a transcript citation shows the speaker and time.
3. Fact rows and the detail panel: a level chip (L1 buyer document, L2 buyer on a call, L3 our side on
   a call, L4 deal notes), `replaced` facts dimmed with "Replaced by <fact>" linking to it,
   `stale` shown as a warning line, `both-sides` shown as "Question and answer: both sides", every
   relation listed in the detail panel ("Replaces …", "Confirmed by …") with "Reject" / "Restore",
   and a "same" group shown as one point with every citation and an "Ungroup" button.
4. Facts filters: Documents and Levels (multi-select), and a toggle "Hide replaced" (on by default in
   a bid).
5. Conflicts: a `document` conflict card shows its reason in words, both facts with their documents
   and levels, the options with what each changes, "Ask the buyer" styled as a third choice, and
   "Settled by <document>" when closed. A `tentative` flag on either fact shows on the card.
6. Download: "CSV for the team" and "CSV to share (no internal sources)".
7. Update `WEB_UI_SPEC.md` (routes and the Documents page) and the README's web section.

### WP10. End-to-end test, per-type evaluation, docs (spec: Build order 10)

Owns: new `tests/test_bid_e2e.py`, new `src/fact_extractor/bideval.py`, `cli.py` (`bid eval`),
`README.md`, `docs/multi-document-design.html` (status line only), `GOAL.md` untouched.
1. `tests/test_bid_e2e.py`: with `ScriptedClient`, a bid of a small made-up RFP (tagged from
   `conftest.sample_pages`), a made-up change addendum cut with the notes cutter standing in for a PDF,
   a transcript and notes: assert the final fact list, levels, the replaced fact, one conflict per
   reason, external CSV.
2. `bideval.py`: scores a bid against a key file (`{"relations": [{from: {doc, unit}, kind, to: [...]}],
   "sides": {speaker: side}, "groups": [[fact text fragments]]}`): relations found, relations applied to
   the right facts, wrong and missed "same" groups, speaker sides. `fact-extractor bid eval BID KEY.json`
   prints the counts. No model call.
3. README: a "Many documents, one bid" section (how to run it from the web and the CLI, what is stored
   where, what is not yet measured: RELATE votes, the review band, the depends question, and that a
   real change or Q&A addendum is still needed to test RELATE). Change the design page's status line
   from "not built" to "built on feature/multi-document-bid; RELATE not yet measured on a real addendum".
