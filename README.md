# fact-extractor

Extracts cited, categorised facts from an RFP PDF for a **bid manager**: who the
buyer is, what the contract says, whether you may bid, what disqualifies you,
the deadlines, how to submit, how proposals are scored, every requirement, and
where the document contradicts itself.

Where the project is heading is in [GOAL.md](GOAL.md): goldset generates the
reference data for an RFP, and DeepEval evaluates the extractor against it.

It is built from the spec in `rfp-fact-extraction-spec.html` (v1, 2 Nov 2026).
That file is **not in this repo**. [REVIEW.md](REVIEW.md) lists every place the
code departs from the spec and why. Read it before changing behaviour.

```
PDF -> tag (IDs + anchor map) -> one round of parallel calls on a cached prefix:
         label every unit (3 votes) | state every unit | find contradictions | find cross-references
    -> majority vote -> facts -> group round (repeats, list items)
    -> stored result (found again by the PDF's content)
```

**A fact is a source unit, not something the model writes.** Every sentence,
heading, list item and table row gets an ID (`p3.7`, `p15.t1r2`) in code, the
same way every time. The model answers one closed question per unit: which
category, or none. So the list of candidate facts and the identity of each fact
do not depend on the model (`units.py`).

**A document is extracted once.** The result is stored under `runs/` and found
again by the PDF's content, so opening the same RFP shows the same facts with
no model call (`results.py`). Two extractions of one PDF still differ on about
one fact in six (which code, or whether a borderline sentence is a fact at
all); storing the result is what makes the Summary and the requirement list the
same every time. `--refresh` extracts again and says what changed.

- Labels are decided by a majority of three votes. A fact whose votes were not
  all the same is marked (`agreement` `2/3`): on Durham, 96% of the facts with
  three equal votes came back identical on a second extraction, against 54% of
  the others.
- A fact's text is a one-line statement written by the model when every number
  in it is in the unit; otherwise the RFP's own words. The source text is
  always on the fact (`source_text`, `citations`).
- `mandatory` and `desirable` are read from the unit's wording in code (shall,
  must, required; should, preferred). `post-award`, `risk` and `unclear` are
  voted.
- `fact_id` is a hash of the document and the unit ID. It does not change with
  the code, the wording or the run.
- A short second round asks the model, per category, which facts state the same
  point and which are items of one list (`group_id`, `group_kind` `same` or
  `list`, `group_title`). Groups only change how facts are shown: the app lists
  a list as one card with its items inside, and a repeated point once with every
  place it is stated. No fact is removed, and a "same" group whose members hold
  different numbers or dates is shown as a list instead. `--no-grouping` skips
  the round.

An earlier pipeline, where the model wrote the facts and code deduped them, was
removed on 2026-11-21. Parts of [REVIEW.md](REVIEW.md) describe it, and the
hand labels in `poc/ablation/labels/` are of its output. See REVIEW.md, "A fact is a labelled source
unit", for why it was replaced.

## Setup

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), and an OpenAI API
key (for `extract`, `golden`, `compare --judge`, `precision --grade` and the
judged DeepEval metrics; every other command works offline).

The quickest start is `./start.sh`. It installs the Python and web dependencies,
creates `.env` from `.env.example` if there isn't one, builds the web UI, and
starts the chat workspace at http://127.0.0.1:8765. Steps that are already done
are skipped, so it is also the everyday way to start it. Extra arguments go to
`fact-extractor web`, e.g. `./start.sh --port 9000`. Node.js/npm is needed
on top of the requirements above.

For work on the code, `./start.sh --dev` skips the build and runs two servers: the
Python server on port 8765 restarts itself when its code changes
(`fact-extractor web --reload`), and the Vite dev server on
http://localhost:5173 reloads the page when `web/src` changes. Open the second one.

By hand:

```bash
uv sync                      # installs deps into .venv
cp .env.example .env         # then edit it
uv run pytest                # sanity check
```

The core dependencies are still `pymupdf` and `openai`. Two optional extras
hold the rest: `web` (FastAPI and uvicorn, for the chat workspace) and `evals` (the
golden-dataset builder's dependencies, LangGraph and LangChain among them, plus
`deepeval`). The dev group installs both, so a plain `uv sync` gives everything.
Without the dev group, ask for what you need: `uv sync --extra evals`,
`uv sync --extra web`. `uv run pyright` type-checks `src/goldset` and
`tests/goldset_builder` only.

`.env` (real environment variables win over it):

| Variable | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | Required for `extract`. |
| `FACT_EXTRACTOR_MODEL` | Model ID for all calls. Default `gpt-6-luna`. `--model` overrides it. |
| `FACT_EXTRACTOR_CHAT_PLANNING` | Chat workspace: `auto` (default; the Decisions API picks per message), `direct`, `light` or `heavy`. See WEB_UI_SPEC.md 7.1. |
| `FACT_EXTRACTOR_CHAT_PLAN_APPROVAL` | Chat workspace: which planning modes show their plan and wait for the customer: `on` (light and heavy, default), `heavy`, `off`. |
| `FACT_EXTRACTOR_DECISIONS_MODEL` | Model for the chat's Decisions API questions. Default `gpt-6-luna`. |
| `FACT_EXTRACTOR_CHAT_COMPOSE_EFFORT` | Chat workspace: reasoning effort of the call that writes the final reply after tool lookups: `low` (default), `medium`, `high`; `off` (or `none`, or empty) skips that call and keeps the loop's own reply. See WEB_UI_SPEC.md 7. |
| `OPENAI_BASE_URL` | Optional proxy or compatible endpoint (read by the `openai` SDK). |
| `LANGSMITH_API_KEY`, `LANGSMITH_TRACING` | Optional. Trace every LangChain call that the golden-dataset builder makes. |
| `DEEPEVAL_TELEMETRY_OPT_OUT` | `1` in `.env.example`: turns off DeepEval's usage telemetry (see "DeepEval suite"). |

## Using it

Work through the commands in this order. The first two cost nothing.

```bash
# 1. What the model will see: the document with an ID on every unit
uv run fact-extractor tag rfp.pdf > tagged.txt

# 2. ID -> page, section, text, bbox (one JSON object per line)
uv run fact-extractor anchors rfp.pdf

# 3. Extract (spends tokens the first time; the stored result after that)
uv run fact-extractor extract rfp.pdf --deal-id deal_442 \
    --out facts.json --report run.json

# 3a. Build a reference list instead of writing one (about 1,300 to 1,600 model
#     calls for all eight categories; see "Reference lists from goldset")
uv run fact-extractor golden rfp.pdf --doc-id rfp-001

# 3b. Score against a reference list by source ID (exact, no model call)
uv run fact-extractor score poc/durham/gold/gold_draft.txt --facts facts.json
uv run fact-extractor score runs/rfp-001/golden/gold.txt --facts facts.json

# 4. Score a run against a hand-written reference list
uv run fact-extractor compare poc/gold/gold_*.txt --facts facts.json --show 10
# ask the model about close calls; verdicts are cached in facts.judge.json
uv run fact-extractor compare poc/gold/gold_*.txt --facts facts.json --judge

# 5. Precision: are the facts right, and worth reading?
uv run fact-extractor precision facts.json --sample 60          # CSV for a person to label
uv run fact-extractor precision facts.json --labels facts.sample.csv --grade

# 6. How far two runs on the same document agree (no model call)
uv run fact-extractor stability facts_a.json facts_b.json
```

Two runs never give the same list: the model's wording, grouping and filing
change each time. `stability` says by how much, on three measures: the source
IDs both runs cite, the codes they file each ID under, and the fact IDs they
share. Read a difference in recall between two configurations against the
difference between two runs of one configuration first. When scoring several
runs with `--judge`, give them one `--judge-cache` file so a pair of texts gets
the same verdict in every run.

`compare` measures recall only. `precision` reports near-duplicate pairs, scores
a labelled sample (`supported` y/p/n, `useful` u/x), and with `--grade` asks the
model the same two questions for every fact (cached in
`poc/precision.grades.json`). The model grades its own extractor's output, so
check its agreement with a labelled sample before trusting it.

The order of work is: extract; build a reference list with `golden` or write
one by hand; then `score`, `compare` and `precision`. The DeepEval suite (see
"DeepEval suite") is another view of the same checks, run on the same facts and
the same reference list; it replaces none of them.

`tag` and `anchors` should be your first stop when results look wrong: if the
text or IDs are off here, no prompt change will fix it.

### `extract` options

| Option | Default | Notes |
| --- | --- | --- |
| `--deal-id` | required | Stored on every fact. |
| `--doc-id` | file name | Part of the stable `fact_id`. |
| `--model` | `$FACT_EXTRACTOR_MODEL` | |
| `--votes` | 3 | Labelling passes per unit; the majority wins. |
| `--store` | `runs` | Where results are kept and looked up. |
| `--refresh` | off | Extract again although this PDF has a stored result; prints what changed. |
| `--no-statements` | off | Show every fact in the RFP's own words. |
| `--no-check` | off | Skip the model's contradiction check. |
| `--no-xref` | off | Skip the cross-reference call (the model finds references, code verifies them). |
| `--no-grouping` | off | Skip the round that groups repeated points and list items. |
| `--parallel` | 48 | Max concurrent calls. |
| `--out` | `-` (stdout) | Facts JSON. |
| `--report` | none | Run report JSON: per-call timing, tokens, cache hits, failures. |

A one-line summary prints to stderr when the run ends, and what changed when an earlier result exists.

### Output

`facts.json` is a list of records:

```json
{
  "fact_id": "f_e76807c241", "deal_id": "deal_442", "doc_id": "rfp-001", "run_id": "run_...",
  "category": "R", "text": "...", "status": "valid",
  "flags": ["mandatory"], "note": "",
  "citations": [{"id": "p3.7", "page": 3, "page_label": "3", "section": "...", "text": "...", "bbox": [0, 0, 0, 0]}],
  "unresolved_ids": [], "problems": [], "conflicts": [], "source_call": "LABEL"
}
```

Categories: `B` buyer info, `C` contract terms, `G` go/no-go gate,
`X` disqualifier, `D` date, `S` submission item, `E` evaluation criterion,
`R` requirement, `Q` contradiction. Flags: `mandatory`, `desirable`, `risk`,
`unclear`, `replaced`, `post-award` (applies only to the bidder who wins). Status: `valid`, `needs_review` (failed validation,
see `problems`), `conflict` (cited by a `Q` fact).

### From code

```python
from fact_extractor import tag_pages, units
from fact_extractor.llm import OpenAIClient
from fact_extractor.pdf import read_pdf

doc = tag_pages("rfp-001", read_pdf("rfp.pdf"))
result = await units.extract(doc, OpenAIClient(), deal_id="deal_442", cfg=units.Config(votes=3))
dates = [f for f in result.facts if f["category"] == "D"]
```

`units.Config` sets votes, parallelism, output caps and which calls run. Any
object with `async complete(request, on_text) -> Response` can replace
`OpenAIClient` (the tests use a scripted fake). `result.report` holds per-call
timing, tokens, cache hits and failures.

## Use as a library

The typed API in `fact_extractor.api` labels units of text you already have, with your own keys and
your own model client. It imports no PDF or model library. The agent harness uses it. Facts come back
citing your keys; nothing is read or written.

```python
from fact_extractor.api import SourceUnit, label_units

units = [
    SourceUnit("u1", "Proposals are due March 3, 2027.", "sentence", 1, "1", "Schedule"),
    SourceUnit("u2", "The vendor must provide 24/7 support.", "list_item", 1, "1", "Requirements"),
]
result = await label_units("rfp-1", units, my_client, votes=3)  # my_client implements llm.LLMClient
for fact in result.facts:
    print(fact.category, fact.unit_keys, fact.flags, fact.status, fact.text)
```

`failed_calls` lists model calls that failed twice (they do not raise); check it before trusting a
sparse result. `document_from_units` gives the tagged document and the short-ID to key map alone.

## Chat workspace (web UI)

The UI, in React with React Spectrum, where a bid manager corrects facts by
chatting or clicking, reads summaries built from the facts, sees what is in the
facts but not in a summary, and chooses between conflicts. The plan and the API are
in [WEB_UI_SPEC.md](WEB_UI_SPEC.md).

`./start.sh` does all of the following. By hand:

```bash
uv sync --extra web
npm --prefix web install
npm --prefix web run build
uv run fact-extractor web --runs runs      # http://127.0.0.1:8765
```

It has eight pages: Documents, Overview (counts, key dates and one row summary per section), Facts
(filters, grouping, CSV download, the cited PDF page), Conflicts, Changes, Report,
Compare and Chat log (what each chat message cost and did, down to the router's
probability for each planning mode). Documents replaces the old New run page
(`#/new` still opens it). A new bid gets its own screen (a name, and files dropped in
straight away); the bid's page then has three numbered steps: 1. Add documents,
2. Check each document (RFP, addenda, call transcripts, deal notes: what each one is,
and who spoke on a call), 3. Extract. It asks for confirmation first, because it spends
API tokens, and shows its progress as a checklist: one line per finished document, the
running document's steps ("Cut into units", "Label the units and build facts", "Link to
earlier documents", ...) with a live clock.

The Changes page is an activity feed: one line per change, what happened, from chat
or the UI and when, with the removed and added words marked inside an edited fact, and a
quiet Undo link.

The chat panel on the right can be resized by dragging its left edge (340 to 960 px,
kept in the browser; double-click resets it). Answers come as a sentence, then a table
or a list when they hold three or more items; the model can also ask the interface to
show a fact's source wording or a timeline of dates, both drawn from the stored facts,
never from text the model writes. A question about a decision (price, bid or no-bid)
looks up what drives it, not only the words of the question, and a turn that used tools
has its final reply written by a second call with reasoning on. When the chat plans
before it acts, the plan shows as a card of numbered steps with the topics each covers,
and a plan waiting for approval has two buttons: "Yes, proceed" and "No, change the
plan" (which opens the steps for editing).

In a bid, the Facts page shows which document and level each fact comes from, dims
facts a later document replaced ("Hide replaced" is on by default), lists the links
between documents with a Reject button, and groups one point stated in several
documents with an Ungroup button. Conflicts between documents show the reason in
words and what each choice changes. Facts has two CSV downloads: one for the team and
one to share, without internal sources. Reject and Ungroup are undone on the Changes
page.

- Corrections never change `facts.json`. They are appended to
  `<run>/workspace/corrections.jsonl`, and every one can be undone on the Changes tab.
- Each section (buyer, submission, gates, scoring, questions, contract, requirements)
  has one summary in fixed rows, each row citing the facts behind it. A row shows the
  model's wording only when it passed the check against the cited facts; otherwise it
  shows those facts. The extraction writes the first five; they start as "extraction"
  rows. A change to a fact in a section, or a decision on a conflict touching it, marks
  the section out of date and rebuilds it in the background. Contract and requirements
  are written only when you ask (Generate or chat). The check of a row's figures reads
  numbers written out in words too ("ninety-five thousand" supports "95,000").
- In a bid, the chat sees a whole point, not one row: a search hit carries its source
  document (and who spoke, on a call), the other rows of its list or table, the facts of
  other documents linked to it and how, and any open conflict. It cites a bid's units as
  `d<no>:<unit ID>`, and a fact it adds whose cited units cannot be found is refused.
- Chat and summaries need `OPENAI_API_KEY`. Everything else works without it.
- For frontend work: `npm --prefix web run dev` (port 5173, proxies `/api` to 8765).

## Many documents, one bid

A bid is one opportunity with several documents: the RFP, addenda, call transcripts and your own
deal notes. Each is read on its own, with the playbook for its type (`src/fact_extractor/playbooks/`),
and then the facts are listed together, in the order the documents were *issued*, never the order
they were uploaded. Design: [docs/multi-document-design.html](docs/multi-document-design.html);
how it was built: [docs/multi-document-build-plan.md](docs/multi-document-build-plan.md).

**From the web:** open Documents, start a bid, drop the files in, check the type, issue number and
date proposed for each (addenda need both), name your team (call speakers on the team list are
proposed as "ours"), confirm each call's speakers, then extract. It shows the planned calls and
asks before spending tokens. The bid then opens like any run, with a document and a level on every fact.

Each speaker of a call is placed on a side: the buyer's, ours, or another party (an advisor, a partner,
a subcontractor). The proposal comes from the team list, then a small model call that reads the call's
attendee list and opening (when an API key is set), then the buyer's facts and the call system's
affiliation. The header's organisation and title are shown beside each name, and you confirm every side.

**From the CLI** (`--store` is the runs folder, default `runs`):

```bash
uv run fact-extractor bid create "Ulster County actuarial"        # prints the bid ID
uv run fact-extractor bid add ulster-county-actuarial RFP.pdf add1.pdf call.json notes.md
uv run fact-extractor bid add ulster-county-actuarial add1.pdf --type change-addendum --number 1 --date 2027-05-20 --yes
uv run fact-extractor bid speakers ulster-county-actuarial 3 "Dana Pike=buyer" "Tom Okafor=ours"
uv run fact-extractor bid show ulster-county-actuarial            # issue order, what each still needs
uv run fact-extractor bid run ulster-county-actuarial             # extract, relate, group, check, build
uv run fact-extractor bid relate ulster-county-actuarial          # ask RELATE again for the units it left unanswered
uv run fact-extractor bid eval ulster-county-actuarial key.json   # score against a hand-made key; no model call
```

`bid add` prints what each file looks like and who suggested it (rules or the model); nothing is
read until you confirm it (`--yes`). Without `OPENAI_API_KEY`, `bid run` builds the list from what
is stored and records the cross-document checks as not done. A unit RELATE gave no usable
answer for is asked again on its own: by `bid relate`, and at the end of every extraction from
the web; the other units keep their stored answers.

**What is stored where.** Each document keeps its own result under `runs/<doc_id>/<run_id>/`, as
for a single RFP, and gains `units.json` (its units, with the speaker's side), and `relations.json`
(what each unit does to the earlier buyer documents) for addenda, calls and notes. The bid is
`runs/_bids/<bid_id>/`: `bid.json` (documents, types, numbers, dates, team, speakers),
`files/` (the uploads), `facts.json`, `report.json` and `conflicts.json` (derived by `bid.build`,
never edited by hand), `groups.json` and `pairs.json` (the answers of the group and pair-check
calls, never asked twice) and `workspace/` (your corrections, as for a run). Corrections never touch
the document results.

**The priority ladder.**
1. Level 1 buyer documents; level 2 the buyer on a call; level 3 our side on a call; level 4 deal notes.
   An adviser the buyer hired counts as the buyer on a call (level 2) when the speakers panel says they act for the buyer; any other outside party is level 3.
2. Between level-1 documents the later issue wins (an addendum's issue number comes before its date),
   unless you confirmed the buyer's order of precedence. Two documents issued together that disagree
   are a conflict, not a replacement.
3. A lower level never changes a higher one: a call or a note that disagrees becomes a conflict
   and both facts stay. A fact with units from both sides (a question answered "yes") is level 2.
4. A fact's text is never rewritten by code. A conflict's first choice may carry an edit, and it is yours to apply.

**Not yet measured.** RELATE (which earlier fact a later unit replaces, confirms or disagrees with)
has only been run on made-up documents: it needs a real change or Q&A addendum, and its answer is a
single vote. The pair check's threshold (0.7), its review band (0.5) and the "depends on the
changed value" question are unmeasured, as is GROUP across documents on real data. Heading detection
reads "1.0 Scope" as a heading but "1. Scope" as a list item, so a section replaced by its heading
may reach further than it should in an RFP numbered that way.

## Reference lists from goldset

`score` and `compare` need a reference list, one `CODE|fact|IDs|flags` line per
fact. Writing one by hand was the slow part: the Ulster and Durham lists took
subagents and reading time. `src/goldset/` is a golden-dataset builder that
produces checked cases for a prompt over a source, and
`src/fact_extractor/golden.py` points it at a tagged RFP and turns what it
accepts back into a reference list. It was copied from the sibling repo
`golden-data-set-builder` at commit `c172c6c` (LangGraph and LangChain). The
copy is tracked in [REVIEW.md](REVIEW.md), 2026-11-20.

**How its loop corrects itself.** For each prompt and source, goldset plans a
todo list, has a worker write one case per item with verbatim quotes as
evidence, and checks every case before it accepts it.

```
plan -> work -> verify -> reconcile --(open items, rounds left)--> work
                                   \--(otherwise)--> finalize
```

- **plan**: the planner picks spans of the source and writes a todo list, each
  item with acceptance criteria.
- **work**: a worker writes the case and its evidence. A second model answers
  the same case blind, for an agreement check.
- **verify**: first code (quotes must appear in the source, no duplicates), then
  the Decisions API (grounded, correct, clear, novel, agrees with the blind
  answer), then, only for the unsure band, an adjudicator that may revise a case.
  A revision is checked again.
- **reconcile**: items out of attempts go to `needs_human.jsonl`. The planner
  reads each failure reason and retries, rewrites, splits or drops the item, and
  adds items for gaps in coverage.

Code owns ids, quote checks, budgets and when the run stops. The planner
proposes; code disposes. Settings (models, gate thresholds, rounds, chunk size,
sweep) are in `goldset.yaml`, every key commented. The full design is in the
source's docstrings and in the original repo's README.

**Two ways in.**

1. **`fact-extractor golden`** builds a reference list for an RFP:

   ```bash
   uv sync --extra evals        # not needed after a plain `uv sync`
   uv run fact-extractor golden rfp.pdf --doc-id rfp-001 \
       [--out DIR] [--codes BCGXDSER] [--cases 30] [--config goldset.yaml]
   ```

   It tags the PDF, writes the tagged text as a goldset source (a page marker
   and block breaks so chunks cut only at page and section boundaries), and
   writes one prompt per category. The case input is one unit ID; the expected
   output is that unit's `CODE|fact|IDs|flags` line, or NONE. The prompts share
   the extractor's category definitions and flag tests (`prompts.DEFINITIONS`,
   `prompts.FLAG_TESTS`, which `units.SYSTEM` is built from); the reader, fact
   and writing rules come from `prompts.SYSTEM`, the old pipeline's prompt,
   which only the golden builder reads. `mandatory` and `desirable` are set
   by code from the unit's wording, as in the extractor. Every accepted line is
   parsed and checked again; one unit accepted under two categories becomes one
   line with alternates (`C/R`).

2. **`goldset run` / `goldset ui`** build a golden dataset for any sources and
   prompts, not only RFPs:

   ```bash
   uv run goldset run examples/goldset/sources examples/goldset/prompts --out runs/my-run
   uv run goldset report runs/my-run
   uv run goldset ui [--port 8501]
   ```

   `examples/goldset/` holds a small order export, a travel policy and two
   prompts; `examples/goldset/large/` holds a generator for a 400-order JSON
   export. Run again with the same `--out` to resume: every model call is cached
   in the run folder.

**Outputs** of `golden`, in `runs/<doc id>/golden/` unless `--out` is given:

| File | Contents |
| --- | --- |
| `gold.txt` | The reference list, in document order. Feed it to `score`, `compare` or `EVAL_GOLD`. |
| `rejected.jsonl` | Accepted cases that could not become a gold line, each with the reason (wrong code, unknown ID, `\|` in the fact). |
| `build/report.md` | goldset's report: accepted first time or after correction, problems, model usage. |
| `build/needs_human.jsonl` | Cases the loop could not settle, with the attempt history. |
| `build/coverage.json` | Per category, the share of the document's chunks that a checked case touches. |

**Cost.** Not measured. From reading the code: about 160 to 200 model calls per
category on a 30-page RFP, so roughly 1,300 to 1,600 for all eight. goldset's
whole-document sweep is part of that; `sweep.enabled: false` in `goldset.yaml`
cuts it, and `--codes` and `--cases` cut the rest.

**Limits.**

- **The list is a checked sample, not every fact.** goldset writes a budgeted
  number of cases per category (default 30, `--cases`), and its planner picks
  which units to cover. `score` against it is recall on that sample. A high
  figure does not mean the extractor found every fact in the RFP.
- **Coverage is not fact coverage.** For a text source, goldset's figure is the
  share of the document's page and section chunks that a checked case touches.
- **Contradictions (`Q`) are not built.** A contradiction cites two places, so
  its case needs two unit IDs in and one line out, which the prompts do not
  have. `--codes` takes `B C G X D S E R`.
- **Never run against the live API.** `fact-extractor golden` has not been run,
  and goldset has only run on a scripted model (the tests). Its thresholds
  (`gate.accept` 0.85, `gate.reject` 0.25), efforts and `--cases 30` are
  untested starting values. Read `gold.txt` and `build/needs_human.jsonl` for
  one RFP, and score a run you know against it, before trusting it as a yardstick.
- The copy in `src/goldset/` and the sibling repo will drift apart.

## DeepEval suite

`src/fact_extractor/evalsuite.py` and `evals/` run the project's own checks
through [DeepEval](https://deepeval.com), so one `deepeval test run` gives a
pass or fail per fact with a reason. `score.py`, `judge.py` and `precision.py`
stay the source of truth. `uv run pytest` does not collect `evals/`.

| Check | DeepEval metric | Model call |
| --- | --- | --- |
| Reference fact found, under its code (`fact-extractor score`) | `ReferenceFound`, which asks `score.score` itself, so it cannot disagree with `score` | No |
| Found fact says what the reference says (`compare --judge`) | `same_fact`, a GEval metric, threshold 0.5 | Yes, 2 calls per found reference fact |
| Extracted fact is backed by its cited text (`precision`, `supported`) | `supported`, DeepEval's FaithfulnessMetric, threshold 1.0 | Yes |
| Extracted fact is worth a bid manager's time (`precision`, `useful`) | `useful`, a GEval metric with the `precision.py` labels, threshold 0.5 | Yes |

```bash
# Was each reference fact found? No model call.
EVAL_FACTS=facts.json EVAL_GOLD=runs/rfp-001/golden/gold.txt \
    uv run deepeval test run evals/test_reference.py

# The same, plus the same_fact judge on found facts (needs OPENAI_API_KEY)
EVAL_JUDGE=1 EVAL_FACTS=facts.json EVAL_GOLD=runs/rfp-001/golden/gold.txt \
    uv run deepeval test run evals/test_reference.py

# Supported and useful, on a seeded sample of the run's facts (needs OPENAI_API_KEY)
EVAL_FACTS=facts.json EVAL_SAMPLE=30 uv run deepeval test run evals/test_facts.py
```

| Variable | Meaning |
| --- | --- |
| `EVAL_FACTS` | `facts.json` of the run to evaluate. |
| `EVAL_GOLD` | One or more reference files, separated by commas. |
| `EVAL_SAMPLE` | Facts judged by `test_facts.py`. Default 30. The sample is the one `precision --sample` draws, so a model grade and a hand label cover the same facts. |
| `EVAL_JUDGE` | `1` adds `same_fact` to `test_reference.py`. |
| `FACT_EXTRACTOR_MODEL` | The judge model. Default `gpt-6-luna`. |

An unset input skips the test with a message.

**Cost.** `test_reference.py` alone: none. With `EVAL_JUDGE=1`: 2 judge calls per
found reference fact. `test_facts.py`: 6 judge calls per fact, so 180 at the
default sample of 30.

**Telemetry.** `evals/conftest.py` and `.env.example` set
`DEEPEVAL_TELEMETRY_OPT_OUT=1`. With no Confident AI login nothing is uploaded;
a run with networking disabled gave the same result. DeepEval writes `.deepeval/`
in the working directory (git-ignored).

**Judge model.** DeepEval 4.3.4 lists `gpt-6-luna` in its OpenAI table. A model
name it does not list would be sent `temperature=0`, which reasoning models
reject; give such a model a `DeepEvalBaseLLM` of its own.

**Not checked.** The three judged metrics have not been run against the live API.
Their thresholds are untested defaults. Compare them with the hand labels in
`poc/ablation/labels/*.csv` before anyone trusts them, as with `precision --grade`.

## Layout

| Module | Spec section |
| --- | --- |
| `pdf.py`, `tagging.py` | 4. Parse and tag |
| `prompts.py` | 10. Prompts: category definitions and tie order (used by `units.py`), and the system prompt `golden.py` reads its fact rules and flag tests from |
| `llm.py` | 5.2, 6.2: request shape, streaming, OpenAI client |
| `validate.py`, `normalize.py` | 6.1, 7. Output format and checks |
| `xref.py` | 8.3 Contradictions: the XREF call finds cross-references, code verifies them |
| `compare.py` | 13. Acceptance: score facts against a reference list |
| `precision.py` | Precision: labelled samples, model grades, near-duplicates |
| `stability.py` | Agreement between two runs on cited IDs, codes and fact IDs |
| `bid.py`, `classify.py`, `cutters.py`, `playbooks/` | A bid of many documents: manifest, issue order, type proposal, one cutter and playbook per type |
| `relate.py`, `ladder.py`, `bidgroup.py`, `reissue.py` | What a later document does to an earlier one, the priority ladder, grouping and pair check across documents, reissued RFPs |
| `bideval.py` | Score a built bid against a hand-made key of relations, groups and speaker sides |
| `units.py` | The unit-label pipeline and its prompts: label votes, statements, contradiction check, facts |
| `results.py` | Stored results on disk, found by PDF content; what a re-extraction changed |
| `score.py` | Recall against a reference list by source ID |
| `golden.py` | Builds a reference list for an RFP with goldset (needs the `evals` extra) |
| `evalsuite.py` | DeepEval test cases and metrics over `score.py` and `precision.py` |
| `web/` (Python) and `web/` (frontend, repo root) | The chat workspace; module by module in WEB_UI_SPEC.md 3 |
| `src/goldset/` | The golden-dataset builder, copied from another repo; its own CLI is `goldset` |

`evals/` holds the DeepEval tests, `examples/goldset/` goldset's examples,
`goldset.yaml` its settings and `tests/goldset_builder/` its tests.

`poc/` holds the hand-written reference lists, `poc/gold/` for the Ulster County RFP and
`poc/durham/gold/gold_draft.txt` for Durham (`CODE|fact|IDs|flags` per line), used by
`score` and `compare`, and the hand labels in `poc/ablation/labels/`. A code may list alternates
(`G/C/R`): the fact is scored under the first, and found under any of them
counts as the same code.

## Gotchas

**Cost and runs**

- **One round of calls, all in parallel.** LABEL (`--votes` times), STATE,
  CHECK and XREF run at once on the same cached prefix; GROUP and BRIEF follow.
  `--parallel` defaults to 48, enough for every call of the round on a ~50-page
  RFP. Lower it if you hit rate limits.
- **A rate-limited call is retried with backoff** up to 5 times. Failed calls
  are listed in the report; the run still completes with what it has.
- **A result is stored and shown again.** `extract` on a PDF it has seen
  returns the stored result with no model call; `--refresh` extracts again and
  says what changed.
- **Prompt caching depends on a byte-identical prefix.** The system prompt and
  tagged document must not change between calls. Put new instructions in the
  task message, never before the document. Reasoning effort is a request
  parameter, so it does not affect the cache. Check `cache_hit_calls_2_to_n` in
  the report; near 0 means the cache is not working (it printed `0.0` in the
  first POC report).

**Input PDFs**

- **Text PDFs only.** Scanned pages with no text layer are not supported (no
  OCR) and silently produce few or no IDs. Check `anchors` first: the number of
  units should look plausible.
- Headings come from font size and bold short lines; tables from PyMuPDF's
  table finder. Odd layouts (multi-column, rotated pages, unusual tables) can
  mis-tag. Look at `tag` output.
- Running headers/footers and page labels are stripped. If a document repeats
  real content on many pages it may be stripped too.
- **IDs are page-local and stable only for the same file.** Re-exporting the
  PDF changes them. A sentence spanning a page break gets the ID of the page
  where it starts.
- Square brackets in source text become `(` `)` and table cells are joined with
  ` ; ` in the tagged text so they cannot be confused with IDs or the `|`
  separator. The anchor map keeps the original text.

**Output quality**

- **The pipeline checks citations and numbers, not truth.** A fact can cite real
  IDs and still be a wrong reading. Review `needs_review` and `conflict` facts
  and spot-check the rest against `citations[].text`.
- Number check: dates, times, money and ordinals are normalised before
  comparison (`March 3, 2027` = `2027-03-03`, `$1.2 million` = `1200000`). A
  number the model computes rather than copies will be flagged.
- Contradictions come from two places: the model's check call and the XREF call
  (the model finds cross-references; `xref.py` verifies them in code: blank,
  missing, retitled, wrong direction, inconsistent attachment names; source
  `XREF`).
- The model is told the audience is a bid manager. The unit-label prompts (in
  `units.py`) have been run on one RFP only (Durham). Run `score` or `compare` on a
  second document before assuming recall holds elsewhere.

**Development**

- `uv run pytest` makes no network calls. It runs 626 tests, all offline;
  goldset's pass on Python 3.11, 3.12 and 3.13.
- `.env` holds a real key. `.gitignore` excludes it; confirm `git status` never
  lists `.env`.
- `load_env` is a minimal parser: `KEY=value` lines, optional quotes and
  `export`, no variable expansion or multi-line values.
- The default model ID `gpt-6-luna` comes from the spec. If the API rejects it,
  set `FACT_EXTRACTOR_MODEL` explicitly.
- `reasoning_effort`, `max_completion_tokens` and `prompt_cache_key` are sent on
  every request. A proxy or older compatible endpoint that rejects them will
  fail every call as `CallFailed`.
