# fact-extractor

Extracts cited, categorised facts from an RFP PDF for a **bid manager**: who the
buyer is, what the contract says, whether you may bid, what disqualifies you,
the deadlines, how to submit, how proposals are scored, every requirement, and
where the document contradicts itself.

It is built from the spec in `rfp-fact-extraction-spec.html` (v1, 2 Nov 2026).
That file is **not in this repo**. [REVIEW.md](REVIEW.md) lists every place the
code departs from the spec and why. Read it before changing behaviour.

```
PDF -> tag (IDs + anchor map) -> plan calls -> parallel extract (cached prefix)
    -> validate -> repair once -> dedupe -> coverage sweep -> contradiction check
    -> in-memory fact store + Decisions hand-off
```

The model never writes quotes or page numbers. Every sentence, heading, list
item and table row gets an ID (`p3.7`, `p15.t1r2`). The model writes short
pipe lines (`R|fact|p3.7,p3.8|mandatory`) and code builds the citation (page,
section, original text, bounding box) from the ID. A fact citing an ID that
does not exist is rejected.

## Setup

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), and an OpenAI API
key (only for `extract`; every other command works offline).

```bash
uv sync                      # installs deps into .venv
cp .env.example .env         # then edit it
uv run pytest                # sanity check
```

`.env` (real environment variables win over it):

| Variable | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | Required for `extract`. |
| `FACT_EXTRACTOR_MODEL` | Model ID for all calls. Default `gpt-6-luna`. `--model` overrides it. |
| `OPENAI_BASE_URL` | Optional proxy or compatible endpoint (read by the `openai` SDK). |

## Using it

Work through the commands in this order. The first three cost nothing.

```bash
# 1. What the model will see: the document with an ID on every unit
uv run fact-extractor tag rfp.pdf > tagged.txt

# 2. ID -> page, section, text, bbox (one JSON object per line)
uv run fact-extractor anchors rfp.pdf

# 3. The planned calls, page ranges and candidate count
uv run fact-extractor plan rfp.pdf

# 4. The real run (spends tokens)
uv run fact-extractor extract rfp.pdf --deal-id deal_442 \
    --out facts.json --report run.json

# 5. Score a run against a hand-written reference list
uv run fact-extractor compare poc/gold/gold_*.txt --facts facts.json --show 10
```

`tag` and `anchors` should be your first stop when results look wrong: if the
text or IDs are off here, no prompt change will fix it.

### `extract` options

| Option | Default | Notes |
| --- | --- | --- |
| `--deal-id` | required | Stored on every fact. |
| `--doc-id` | file name | Part of the stable `fact_id`. |
| `--model` | `$FACT_EXTRACTOR_MODEL` | |
| `--parallel` | 16 | Max concurrent calls. |
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
`unclear`, `replaced`. Status: `valid`, `needs_review` (failed validation twice,
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
| `store.py` | 9. Store (in memory, not MongoDB) |

`poc/` holds output from proof-of-concept runs on the Ulster County RFP
(`facts_run*.json`, `report_run*.json`) and the reference list in `poc/gold/`
(`CODE|fact|IDs|flags` per line) used by `compare`. A code may list alternates
(`G/C/R`): the fact is scored under the first, and found under any of them
counts as the same code.

## Gotchas

**Cost and runs**

- **Every call runs twice by default** (`Config.passes = 2`) and the union is
  kept, for recall. A run on a ~50-page RFP is roughly 40 model calls, plus
  sweep chunks and a check. The second pass reads the cached document prefix,
  but you still pay for the output tokens.
- **`--parallel` is 16 on the CLI but `Config.max_parallel` is 32.** The CLI
  value wins when you use the CLI. With 2 passes, 16 means calls queue; raise it
  if `queue_seconds` in the report is not zero, lower it if you hit rate limits.
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
- `fact_id` is a hash of doc, category, IDs and normalised text. It is stable
  across reruns, but if the model words a fact differently it gets a new ID.
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

- `uv run pytest` makes no network calls. At the time of writing 43 pass and
  `tests/test_pipeline.py::test_sweep_all_includes_sentences_without_candidate_words`
  fails; fix or update it before relying on the suite.
- `.env` holds a real key. `.gitignore` excludes it, but **this directory is not
  a git repository yet**, so run `git init` before the first commit and confirm
  `git status` does not list `.env`.
- `load_env` is a minimal parser: `KEY=value` lines, optional quotes and
  `export`, no variable expansion or multi-line values.
- The default model ID `gpt-6-luna` comes from the spec. If the API rejects it,
  set `FACT_EXTRACTOR_MODEL` explicitly.
- `reasoning_effort`, `max_completion_tokens` and `prompt_cache_key` are sent on
  every request. A proxy or older compatible endpoint that rejects them will
  fail every call as `CallFailed`.
