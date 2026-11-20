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
         label every unit (3 votes) | state every unit | find contradictions
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

The earlier pipeline, where the model wrote the facts, is still there as
`extract --legacy` and is what most of this README below and of
[REVIEW.md](REVIEW.md) describes. See REVIEW.md, "A fact is a labelled source
unit", for why it was replaced.

## Setup

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), and an OpenAI API
key (for `extract`, `golden`, `compare --judge`, `precision --grade` and the
judged DeepEval metrics; every other command works offline).

```bash
uv sync                      # installs deps into .venv
cp .env.example .env         # then edit it
uv run pytest                # sanity check
```

The core dependencies are still `pymupdf` and `openai`. Two optional extras
hold the rest: `ui` (Streamlit, for the review app) and `evals` (the
golden-dataset builder's dependencies, LangGraph and LangChain among them, plus
`deepeval`). The dev group installs both, so a plain `uv sync` gives everything.
Without the dev group, ask for what you need: `uv sync --extra evals`,
`uv sync --extra ui`. `uv run pyright` type-checks `src/goldset` and
`tests/goldset_builder` only.

`.env` (real environment variables win over it):

| Variable | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | Required for `extract`. |
| `FACT_EXTRACTOR_MODEL` | Model ID for all calls. Default `gpt-6-luna`. `--model` overrides it. |
| `OPENAI_BASE_URL` | Optional proxy or compatible endpoint (read by the `openai` SDK). |
| `LANGSMITH_API_KEY`, `LANGSMITH_TRACING` | Optional. Trace every LangChain call that the golden-dataset builder makes. |
| `DEEPEVAL_TELEMETRY_OPT_OUT` | `1` in `.env.example`: turns off DeepEval's usage telemetry (see "DeepEval suite"). |

## Using it

Work through the commands in this order. The first three cost nothing.

```bash
# 1. What the model will see: the document with an ID on every unit
uv run fact-extractor tag rfp.pdf > tagged.txt

# 2. ID -> page, section, text, bbox (one JSON object per line)
uv run fact-extractor anchors rfp.pdf

# 3. The planned calls, page ranges and candidate count
uv run fact-extractor plan rfp.pdf

# 4. Extract (spends tokens the first time; the stored result after that)
uv run fact-extractor extract rfp.pdf --deal-id deal_442 \
    --out facts.json --report run.json

# 4a. Build a reference list instead of writing one (about 1,300 to 1,600 model
#     calls for all eight categories; see "Reference lists from goldset")
uv run fact-extractor golden rfp.pdf --doc-id rfp-001

# 4b. Score against a reference list by source ID (exact, no model call)
uv run fact-extractor score poc/durham/gold/gold_draft.txt --facts facts.json
uv run fact-extractor score runs/rfp-001/golden/gold.txt --facts facts.json

# 5. Score a run against a hand-written reference list
uv run fact-extractor compare poc/gold/gold_*.txt --facts facts.json --show 10
# ask the model about close calls; verdicts are cached in facts.judge.json
uv run fact-extractor compare poc/gold/gold_*.txt --facts facts.json --judge

# 6. Precision: are the facts right, and worth reading?
uv run fact-extractor precision facts.json --sample 60          # CSV for a person to label
uv run fact-extractor precision facts.json --labels facts.sample.csv --grade

# 7. How far two runs on the same document agree (no model call)
uv run fact-extractor stability facts_a.json facts_b.json
```

Two runs never give the same list: the model's wording, grouping and filing
change each time. `stability` says by how much, on three measures: the source
IDs both runs cite, the codes they file each ID under, and the fact IDs they
share. Read a difference in recall between two configurations against the
difference between two runs of one configuration first. When scoring several
runs with `--judge`, give them one `--judge-cache` file so a pair of texts gets
the same verdict in every run (`poc/ablation/score.sh` does).

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
| `--legacy` | off | The earlier pipeline. The options below this row apply to it only. |
| `--parallel` | 48 (legacy 32) | Max concurrent calls. |
| `--passes` | 1 | Run every extraction call this many times and keep the union. 2 adds 0-3 points of recall for ~60% more output tokens. |
| `--max-output-tokens` | 3000 | Output cap per extraction call. A cut call is split and rerun. |
| `--no-sweep` | off | Turn the sweep off, for trimming tests (`poc/ablation/`). |
| `--sequential-check` | off | Run the contradiction check after the sweep so it sees sweep facts. Slower. |
| `--out` | `-` (stdout) | Facts JSON. |
| `--report` | none | Run report JSON: per-call timing, tokens, cache hits, failures. |

A one-line summary and latency stats print to stderr when the run ends.

### Output

`facts.json` is a list of records:

```json
{
  "fact_id": "f_e76807c241", "deal_id": "deal_442", "doc_id": "rfp-001", "run_id": "run_...",
  "category": "R", "text": "...", "status": "valid",
  "flags": ["mandatory"], "note": "",
  "citations": [{"id": "p3.7", "page": 3, "page_label": "3", "section": "...", "text": "...", "bbox": [0, 0, 0, 0]}],
  "unresolved_ids": [], "problems": [], "conflicts": [], "source_call": "R2"
}
```

Categories: `B` buyer info, `C` contract terms, `G` go/no-go gate,
`X` disqualifier, `D` date, `S` submission item, `E` evaluation criterion,
`R` requirement, `Q` contradiction. Flags: `mandatory`, `desirable`, `risk`,
`unclear`, `replaced`, `post-award` (applies only to the bidder who wins). Status: `valid`, `needs_review` (failed validation,
see `problems`), `conflict` (cited by a `Q` fact).

### From code

```python
from fact_extractor import InMemoryFactStore, RecordingDecisions, extract, tag_pages
from fact_extractor.llm import OpenAIClient
from fact_extractor.pdf import read_pdf

doc = tag_pages("rfp-001", read_pdf("rfp.pdf"))
store = InMemoryFactStore()
result = await extract(doc, OpenAIClient(), deal_id="deal_442", store=store, decisions=RecordingDecisions())
store.find(deal_id="deal_442", category="D")
```

Pass a `Config(...)` as `cfg=` to change parallelism, passes, sweep size and so
on. Any object with `async complete(request, on_text) -> Response` can replace
`OpenAIClient` (the tests use a scripted fake). Any object with
`async submit(conflict: dict)` can replace `RecordingDecisions`, which stands in
for the Decisions API.

## UI

A Streamlit app for reading a run: check any fact against its PDF page, and take
the lists a bid manager acts on out as CSV. It reads what `extract` writes and
never changes a run it opens.

```bash
uv sync --extra ui          # Streamlit is an optional extra
uv run fact-extractor ui    # [--port 8501]
```

The app reads runs from one folder, `runs/`, laid out as
`runs/<doc_id>/<run>/facts.json`, and lists them newest first. That is where
`extract` and the New run tab store results. The earlier pipeline's runs from
`poc/ablation/` were moved there on 2026-11-18 and are marked "earlier
pipeline" in the list. The PDF is `source.pdf` beside the run, or one level up
in the document's folder; otherwise pick one from the working directory or
upload it. Start the app from the project folder.

| Tab | For |
| --- | --- |
| Summary | Six sections for a bid manager, each a short summary in fixed rows that the model writes at extraction from that section's facts: **buyer information**, **submission instructions**, **go/no-go gates**, **scoring criteria** and **clarifications**, plus a **calendar** table built in code from the date facts. Every row cites the facts it rests on; a row with a number that is not in those facts is replaced by the facts themselves, and a row with nothing says so. The facts behind a section are folded under it. Built from the stored result; opening it calls no model. |
| Facts | A reading list of clickable fact cards beside the source: a Bid / After award View switch, type chips with counts, search, and more filters (status, flag, pages); open a fact to see its citations highlighted on the PDF page; download the filtered list as CSV (UTF-8 with BOM, opens in Excel). |
| Run report | Engineer: stage timings, tokens, cache hit rate, and each call's log and raw output. |
| Compare runs | `stability` for two runs of the same document, plus the source IDs filed under different codes. |
| New run | Starts `extract` from the app, after a confirmation that it spends tokens. Writes `runs/<doc_id>/<run_id>/` (`facts.json`, `report.json`, `source.pdf`). |

No other tab calls the model. The layout is in `src/fact_extractor/ui/app.py`;
loading, filtering, CSV and page rendering are in `ui/data.py` (no Streamlit
import), and the screens are specified in `UI_SPEC.md`.

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
   output is that unit's `CODE|fact|IDs|flags` line, or NONE. The prompts reuse
   the extractor's category definitions, fact rules and flag tests
   (`prompts.py`) and change none of them. `mandatory` and `desirable` are set
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

**Measured.** On the Ulster reference list (`poc/gold/gold_c.txt`, 88 facts)
against the stored `stable` run, `deepeval test run` passed 80 and
`fact-extractor score` reports 80 under the same code (83 found). That is one
run on one list, and only the metric that makes no model call.

**Not checked.** The three judged metrics have not been run against the live API.
Their thresholds are untested defaults. Compare them with the hand labels in
`poc/ablation/labels/*.csv` before anyone trusts them, as with `precision --grade`.

## Layout

| Module | Spec section |
| --- | --- |
| `pdf.py`, `tagging.py` | 4. Parse and tag |
| `planner.py` | 5. Plan calls |
| `prompts.py` | 10. Prompts (system prompt and tasks) |
| `llm.py` | 5.2, 6.2: request shape, streaming, OpenAI client |
| `validate.py`, `normalize.py` | 6.1, 7. Output format and checks |
| `merge.py` | 8. Dedupe and coverage |
| `xref.py` | 8.3 Contradictions: cross-references checked in code |
| `compare.py` | 13. Acceptance: score facts against a reference list |
| `pipeline.py` | 3, 8, 11, 12: orchestration and failures |
| `precision.py` | Precision: labelled samples, model grades, near-duplicates |
| `stability.py` | Agreement between two runs on cited IDs, codes and fact IDs |
| `units.py` | The unit-label pipeline: label votes, statements, contradiction check, facts |
| `results.py` | Stored results on disk, found by PDF content; what a re-extraction changed |
| `score.py` | Recall against a reference list by source ID |
| `store.py` | 9. Store (in memory, not MongoDB) |
| `golden.py` | Builds a reference list for an RFP with goldset (needs the `evals` extra) |
| `evalsuite.py` | DeepEval test cases and metrics over `score.py` and `precision.py` |
| `src/goldset/` | The golden-dataset builder, copied from another repo; its own CLI is `goldset` |

`evals/` holds the DeepEval tests, `examples/goldset/` goldset's examples,
`goldset.yaml` its settings and `tests/goldset_builder/` its tests.

`poc/` holds output from proof-of-concept runs on the Ulster County RFP
(`facts_run*.json`, `report_run*.json`) and the reference list in `poc/gold/`
(`CODE|fact|IDs|flags` per line) used by `compare`. A code may list alternates
(`G/C/R`): the fact is scored under the first, and found under any of them
counts as the same code.

## Gotchas

**Cost and runs**

- **One pass by default.** A run on a ~50-page RFP is roughly 15 extraction
  calls, plus sweep chunks and a check. `--passes 2` runs every call twice and
  keeps the union: 0-3 points more recall in the trimming tests, about 60% more
  output tokens and 15-20 s more.
- **No repair call.** A line that fails validation (unknown ID, number not in
  the cited text) is kept as `needs_review` with the reason in `problems`.
- **`--parallel` defaults to 32**, enough for every call of two passes at once
  on a ~50-page RFP. Raise it if `queue_seconds` in the report is not zero,
  lower it if you hit rate limits.
- **A 429 halves the concurrency limit for the rest of the run** and retries
  with backoff (5 times). Failed calls are listed in `failed_calls` in the
  report; the run still completes with what it has.
- **Prompt caching depends on a byte-identical prefix.** The system prompt and
  tagged document must not change between calls. Put new instructions in the
  task message, never before the document. Reasoning effort is a request
  parameter, so it does not affect the cache. Check `cache_hit_calls_2_to_n` in
  the report; near 0 means the cache is not working (it printed `0.0` in the
  first POC report).
- **Output is capped at 3,000 tokens per call.** A cut call is split (by page
  range for `R`/`K`, by category for `A`/`B`/`C`) and rerun, up to 3 times. If
  it is still cut, valid lines are kept and the call is marked `partial` in the
  report. Check for `partial` before trusting recall.

**Input PDFs**

- **Text PDFs only.** Scanned pages with no text layer are not supported (no
  OCR) and silently produce few or no IDs. Check `anchors` or `plan` first: the
  `ids` count should look plausible.
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
- Dedupe merges facts with the same code and IDs only when the text is also
  similar (>= 0.6), so one sentence can legitimately yield several facts.
  Facts with different codes merge only when they have the same main (first)
  ID and one plainly restates the other; the code that comes first in
  `prompts.PRECEDENCE` is kept.
- `fact_id` is a hash of doc, category and the main (first) cited ID, plus a
  counter when several facts share those. It does not depend on wording, so
  about 60% of facts keep their ID on a rerun (5% when it hashed the text). It
  changes when the model files the sentence under another code or cites a
  different main ID, and the counter follows list order: when one sentence gives
  two R facts in one run and three in the next, the same ID can name a
  different one of them. IDs written before 2026-11-18 used the old hash.
- **The store is in memory.** Nothing persists unless you write `--out`.
  Decisions are collected by `RecordingDecisions`, not sent anywhere.
- Contradictions come from two places: the model's check call and `xref.py`
  (cross-references to blank or retitled articles and sections, source `XREF`).
  With the default parallel check, facts added by the sweep are not seen by the
  model check; use `--sequential-check` if that matters.
- The model is told the audience is a bid manager. Prompts in `prompts.py` are
  tuned on one RFP (Ulster County). Run `compare` on a second document before
  assuming recall holds elsewhere.

**Development**

- `uv run pytest` makes no network calls. It runs 174 tests (113 for the
  extractor, 19 for goldset, 31 for `golden.py`, 11 for `evalsuite.py`), all
  offline; goldset's pass on Python 3.11, 3.12 and 3.13.
- `.env` holds a real key. `.gitignore` excludes it; confirm `git status` never
  lists `.env`.
- `load_env` is a minimal parser: `KEY=value` lines, optional quotes and
  `export`, no variable expansion or multi-line values.
- The default model ID `gpt-6-luna` comes from the spec. If the API rejects it,
  set `FACT_EXTRACTOR_MODEL` explicitly.
- `reasoning_effort`, `max_completion_tokens` and `prompt_cache_key` are sent on
  every request. A proxy or older compatible endpoint that rejects them will
  fail every call as `CallFailed`.
