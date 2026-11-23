# Review: RFP fact extraction spec (v1, 2 Nov 2026), and decisions since

Where the code departs from the spec, and why, followed by a log of changes and
measurements. The spec's pipeline (the model wrote facts, code deduped them) was
replaced by the unit-label pipeline on 2026-11-18 and removed on 2026-11-21; the
review notes that only concerned it were removed with it.

## Spec departures still in the code

1. **Number check 7.3 fails correct facts.** The output rules ask the model to
   *reformat* (dates as YYYY-MM-DD) while the check wants every number to
   "appear in the cited text". "5 PM" vs "5:00 PM", "March 3, 2027" vs
   "2027-03-03", "$1,200,000" vs "1200000", "$1.2 million" all need
   normalisation, not just "dates and number formats". *Decision:* both sides
   are reduced to a canonical token set (ISO dates, 24h times, plain decimals
   with scale words applied, ordinals stripped). The cited text set also
   includes the section heading of each cited ID, so "Section 4.2" in a fact
   passes when the cited sentence sits under heading 4.2.
2. **Escaping.** If RFP text itself contains `[p3.1]`-style brackets or a line
   starting with `[`, the tagged document becomes ambiguous and the model can
   cite a fake ID that then *exists in text but not the map*. Also, table cells
   are joined with ` | ` (4.2 example) while `|` is the output separator, so
   the model is primed to copy `|` into facts. *Decision:* square brackets in
   source text are rendered as `(`…`)`, and table cells are joined with ` ; `
   in the tagged text. Anchor-map `text` keeps the original.
3. **Cache warm-up (5.2)** "start the others when the first begins to stream"
   — the cache entry is written when the prefix is processed, which is before
   the first output token, so waiting for the first streamed token is the
   right signal. Implemented exactly that way, with a timeout fallback so a
   slow first call does not serialise the run.
4. **Status `conflict`** is listed but never assigned by any step.
   *Decision:* facts cited by any Q line from the check get status
   `conflict` (and keep the Q line ID in a `conflicts` field).
5. **Multi-page sentences / tables.** A sentence that runs over a page break
   gets the ID of the page where it starts; a table continued on the next
   page restarts row numbering on the new page (IDs stay page-local) and
   reuses the header from the previous page if the new fragment has none.
6. **Category E, evaluation criteria** (not in the spec): each criterion with
   points or weight, screening, price scoring, interviews. The spec had no place
   for how proposals are scored.
7. **Flags** (`models.FLAGS`): `mandatory`, `desirable`, `risk`, `unclear`,
   `replaced` and `post-award` (see "Before the bid and after award"), stored as
   a `flags` list on each fact; free text stays in `note`.

- "Keep numbers and units as in the source" (6.1) vs "Dates as YYYY-MM-DD":
  dates are the one exception.

## Changes and measurements

### Scoring against a reference list

**Matcher fix (2026-11-11).** The first scores came from a lenient matcher: one
extracted fact could count for several gold facts (run 9: 555 matches from 425
facts, one used 7 times), the category and citation bonuses could carry a match
with almost no shared words, and overlap was measured against the shorter text,
so short vague facts scored high. Now matching is one-to-one (best pairs
first), bonuses only break ties, and text similarity must reach 0.4 measured
against the gold fact's words. Run 9 drops from 95.7% to 72.1% found under some
code; 89 of the new misses are gold facts folded into an extracted fact already
matched elsewhere (column `merged`).

**Value check (2026-11-11).** Each matched pair now also compares dates, times,
amounts and counted durations ("five working days"): `ok`, `wrong` (a different
value of the same kind) or `incomplete` (value left out). `recall_values_ok`
counts a gold fact only when it is found with every value. Runs 1–9 have no
wrong deadlines or amounts; the few `wrong` verdicts are pairs the matcher got
wrong (e.g. a valuation-years fact paired with the contract-term fact), and the
`incomplete` ones are mostly real omissions (umbrella minimum $2,000,000,
invoices within 120 days, 30-day extension notice). Run 9: 72.1% found, 69.3%
found with values ok. Values are parsed by `normalize.values`, so anything it
does not read (spelled-out amounts, "the 15th") is not checked.

**Reference list deduplicated, combined facts credited (2026-11-14).** The
three subagents that wrote `poc/gold/` often wrote the same fact into their own
files under different codes (an insurance minimum as G in `gold_bdgsx`, C in
`gold_c` and R in `gold_r`). With one-to-one matching only one copy could ever
be found, so each duplicate was a guaranteed miss. Duplicates were merged with
this rule: lines from different files that share an ID, similarity >= 0.55
both ways, the same values, Q only with Q, and never two lines of one file in a
group (each file's lines are deliberately distinct, e.g. separate certificate
fields). 92 groups, 580 -> 467 facts. The kept line is the one from the most
specific file (bdgsx, then c, then r), with the IDs and flags of the group and
the other codes as alternates (`G/C/R|...`): a fact extracted under any listed
code counts as the same code.

`compare` also credits a gold fact as `combined` when an extracted fact already
paired with another gold fact states it too (shares an ID, holds >= 60% of its
content words, values agree), e.g. one fact listing all three local-preference
tiers. Run 9: 81.2% found under some code (was 72.1%), 78.2% with values ok;
26 combined, 21 still `merged`. G recall rose from 50% to 82%: most gate facts
had been duplicates of R facts. Remaining limits: values in a list after one
month ("December 31, 2026, 2027 and 2028") parse as one date plus bare years,
so a fact stating only part of such a list can show as `wrong`; and paraphrases
just under the 0.4 cutoff still count as misses.

**LLM judge for close calls (2026-11-14).** `compare --judge` (judge.py) asks
the model about pairs near the cutoff: unmatched gold facts with a candidate on
the same IDs scoring 0.2–0.4 (best 3), and matches scoring below 0.5. Verdicts
are `full`, `partial` (main point there, a detail missing) or `no` (another fact
or another value). `full`/`partial` may match below the cutoff, `no` never
matches. Verdicts are cached by text in `<facts>.judge.json`, so reruns cost
nothing and score the same; scoring is rerun until no new close pair appears.
A first yes/no prompt judged inconsistently: it rejected wording matches for a
missing signature yet accepted a three-attachment fact from "listed in
Attachment A". Three verdicts fixed that. Run 9 (141 pairs, 5 calls, ~35 s):
88.7% found, 78.6% without partials; 34 matched below the cutoff, 1 wording
match rejected, 47 partial. `partial` is generous (it once covered "submit the
non-collusion affidavit" for "enclose written authorization if the signer is
not the price decision-maker"), so quote both numbers. Pairs scoring >= 0.5
are never judged, so some partial matches hide there.

### Cross-reference check (model finds, code verifies)

One extra call per document (`XREF`, in the same round as the label, state and
check calls, on the same cached document) lists every reference to another part
of the document, an attachment or an outside source, with the unit it points at:
`REF|unit|reference text as written|target unit or none|kind`, kind being
section, attachment or external, and an `END|count` line. The model never says
what is wrong. `xref.py` then verifies each line in code. A line whose unit does
not exist or whose reference text is not in that unit is dropped. A Q fact
(source `XREF`, one per problem) is written only when code can show it:

- a. the target unit does not exist;
- b. the target is blank ("intentionally left blank", "reserved", "not used");
- c. a section reference with target none that names a number, letter or quoted
  title, or an attachment reference that says it is in this document ("below",
  "this RFP") and is not; and a reference left blank ("refer to" and nothing,
  empty brackets, underscores);
- d. the reference quotes or parenthesises a title and fewer than half of its
  words are in the target;
- e. it says above or below and the target is on the other side;
- f. across the document, one attachment identifier with two different names, or
  one name with two identifiers: one fact listing every place.

External references are never errors, and an attachment that is not in the PDF
is not an error by itself (often supplied separately). The report has
`xref`: status (ok, failed, unparseable, off), references found, dropped,
external, checked, verified and problems. A failed call leaves the run intact
with no XREF facts. `--no-xref` skips the call.

Why: the first version found references by regex ("Article N", "Section N")
and matched headings starting with the same words. On the two test RFPs it
caught 1 of 9 real reference mistakes, because most headings and references
have no such shape (docs/xref-measurement.md). The Article 17 case it did catch
(the survival clause citing an article that is "INTENTIONALLY LEFT BLANK") is
rule b. Q facts from XREF and CHECK on the same units merge into one fact
(source `CHECK,XREF`).

Not measured yet: how many of the 9 mistakes the new call finds on the two test
RFPs (needs a real run).

### Run-to-run stability (2026-11-18)

Two runs of one configuration on one RFP give different fact lists. The code is
not the source: tagging the same PDF twice gives the same bytes, the call plan
is fixed, and nothing in the pipeline is random. The request sets no temperature
or seed (`llm.py`) and extraction runs at low reasoning effort, so every call is
a fresh sample.

`fact-extractor stability a.json b.json` reports how far two runs agree on cited
IDs, codes per ID and fact IDs. Read a difference between two configurations
against the difference between two runs of one configuration first.

### Before the bid and after award (2026-11-18)

A bid manager reads an RFP for two different things: what to know, decide and
submit before the deadline, and what the winner must do afterwards. The nine
categories say what a fact is about, not when it applies, so the two were
mixed: in the Durham RFP section 3.8 (insurance) is written as "Contractor
agrees to..." and asks for nothing with the proposal, yet "name the City as
additional insured" was filed as a go/no-go gate. An after-award obligation
matters before the bid only when it decides whether to bid, belongs in the
price, or is a term to object to.

*Changes (departures from the spec's prompt 10.1 and flag list):*

1. **New flag `post-award`** (rule 14 of the system prompt): the fact applies
   only to the bidder who wins. It can stand next to other flags.
2. **G is narrowed** to conditions the bidder must meet by submission. A duty
   that starts after award is a C fact with `post-award`.
3. **The UI has a View switch** on Overview and Facts: *Bid* hides `post-award`
   facts unless they have the `risk` flag or state an amount (these are listed
   as "After award, but price or decide it now"); *After award* shows only
   `post-award` facts.

### General principles, not point fixes (2026-11-18)

Patching a prompt case by case (an insurance example in one definition, a clause
for one kind of fact in a rule) fixed the RFP it was written for and moved the
variation elsewhere. The system prompt in `prompts.py` (`SYSTEM`, read today only
by `golden.py` for its fact rules and flag tests) was rebuilt from statements that
hold for any RFP, in this order:

1. **The reader**: three moments a fact can serve (deciding to bid, writing and
   submitting, after winning).
2. **What a fact is**: one point, a unit of meaning and not a sentence.
   Neighbouring sentences that make one point give one fact citing all of
   them; one sentence with several points gives several; each point once.
3. **Categories**, each defined without flag rules or exceptions, then the
   one-code order.
4. **Flags**, each with a test that applies to a fact of any code. Post-award:
   "would a bidder who does not win ever have to do, hold, or respect this?"
5. **Citations** and **writing** rules.

### A fact is a labelled source unit: trial (2026-11-18)

The pipeline asks the model to write facts, so the model decides which
sentences to use, how to group them, the code and the wording, and no two runs
give the same list. Over 14 Durham runs, of 578 tagged units 315 were used by
every run, 119 by none and 144 by some. The reference list has one fact per
main ID for 219 of its 227 main IDs.

Trial (`poc/unit_trial/trial.py`, since deleted: it became `units.py`; Durham
only, nothing in `src/` changed): the model writes no facts. For every unit it gives a label (a code, `=` for a
continuation of the unit before, `-` for nothing) and flags; three votes per
unit, majority wins; the whole thing run twice (A and B). Scored by source ID
against the reference list, with the current pipeline scored the same way.

| | Unit labels, 3 votes (A, B) | Current pipeline (8 runs today) |
| --- | --- | --- |
| Reference facts whose main ID is used | 0.983, 0.983 | 0.962 to 0.992 |
| ... and under the reference code | 0.874, 0.836 | 0.52 to 0.82 |
| Seconds | 21.0, 26.8 | 35 to 59 |
| Output tokens | 32.6k, 32.3k (three votes) | 23k to 30k |
| Two results agree a unit is used | 0.969 | 0.92 (single runs) |
| Two results agree on its code | 0.900 (58 units differ) | 0.81 to 0.84 (single runs) |

- **Passed:** time (under 30 s) and recall (equal to the current pipeline, not
  better).
- **Failed:** the 97% agreement target, on codes. Voting lifts code agreement
  from 0.84 (single labelling passes) to 0.90, not further.
- **Disagreement is concentrated and visible.** 382 units got the same label
  from all three votes in both runs, and 373 of them (97.6%) ended with the
  same code. 49 of the 58 differences are on units where the votes were split.
  A split vote is a usable "check this" marker.
- **What differs is the code, not the sentence:** R against S on 15 units, C
  against R on 11; 18 of the 58 are used in one run and not the other.
- **Flags do not settle by vote:** mandatory agrees on 96 of 146 units flagged
  in either run, post-award on 28 of 57, risk on 25 of 26. Mandatory and
  desirable follow the modal verb of the sentence and could be set in code.
- The output-token estimate before the trial (about 5k per pass) was wrong:
  hidden reasoning makes a pass about 11k.

### Rebuilt on labelled units (2026-11-18)

After the trial the pipeline was rebuilt as proposed (`units.py`, `results.py`,
`score.py`); `extract` uses it by default and the earlier pipeline is
`extract --legacy`. Departures from the spec: sections 5 to 8 (call plan, model
output format, sweep, dedupe) do not apply to the new path; section 9's store is
a folder on disk.

- **One round of calls**, all on one cached prefix: every unit labelled three
  times, every unit stated once, one contradiction check. The check no longer
  gets the list of facts, because that would make it a second round.
- **A fact** is a coded unit plus the units labelled as its continuation (at
  most three units back). `fact_id` = hash of (doc_id, unit ID).
- **Text**: the model's statement for the unit when every number in it is in
  the fact's units, else the RFP's words.
- **`mandatory` / `desirable`** from the main unit's wording, in code.
- **Stored results**: `runs/<doc_id>/<run_id>/` with `facts.json`,
  `report.json`, `labels.json`, `source.pdf`, `meta.json`; looked up by (PDF
  sha256, pipeline version, doc_id). `extract` shows the stored result unless
  `--refresh`.
- **Scoring by ID**: `fact-extractor score`. The fuzzy `compare` and the judge
  remain for the legacy runs.

*Durham, two extractions of the same PDF (`runs/durham-rfp24-0031/`):*

| | First | Second (`--refresh`) |
| --- | --- | --- |
| Seconds | 27.3 | 33.4 |
| Facts | 380 + 2 Q | 381 + 3 Q |
| Reference facts found, by main ID | 0.979 | 0.962 |
| ... under the reference code | 0.878 | 0.845 |
| Facts with three equal votes | 310 | 257 |
| Output tokens | 49.8k | 50.8k |
| Asking again without `--refresh` | 0.2 s, no model call | |

- **Recall and time are where the earlier pipeline was or better** (recall
  0.96 to 0.99 by the same measure, 35 to 59 s).
- **Two extractions are not the same list**: 357 facts are on the same unit in
  both, 337 of them with the same code; 23 and 24 are in one result only. That
  is 83% identical over all facts, in line with the trial. The stored result
  is what makes a document's facts the same each time it is opened.
- **Equal votes predict stability**: of the first result's 310 facts with
  three equal votes, 299 (96%) are in the second with the same code; of its 70
  split facts, 38 (54%).
- **Costs**: output tokens doubled (about 50k against 23k to 30k), two thirds
  of it the three label votes. The statements differ in wording between
  extractions (64 of 337 word for word the same), which the store hides.
- **Worse than before**: the contradiction check finds fewer (2 and 3 Q facts;
  1 of the 3 reference contradictions) now that it works without the fact
  list. `mandatory` by wording is narrower than the model's flag was: 66 facts
  against 140 to 250, because an instruction such as "Describe your approach"
  has no modal verb.
- **Not done**: Ulster has not been run on the new pipeline; the fixed "bid
  sheet" of named Summary rows from the proposal is not built (the Summary
  still lists facts by category); the legacy code is not removed.

### Table text, and groups for reading (2026-11-18)

Two problems showed on the Summary and Facts screens once every unit could be
a fact.

**Table rows were unreadable.** PyMuPDF's `table.extract()` joins a cell's
characters without the gaps between words ("TheproponentmustbeanOracleapproved"),
spacer columns gave "Column 1: ; Column 3: ", and a cell wrapped over two lines
became two rows. *Change (`pdf.py`, `tagging.py`):* cell text is built from
`page.get_text("words")`; each word goes to the nearest row and that row's
nearest cell, and each cell to the header column it overlaps most; empty
columns and empty cells are left out of the row text. Durham went from 578 to
572 units (six wrapped fragments joined their rows); Ulster keeps its 849 unit
IDs. The statement for a table row now passes the number check ("Section 4.1"
against "section41" before), so the raw row is no longer shown.

**The lists repeated themselves.** One fact per unit means a 21-row table of
Oracle modules is 21 cards with one sentence frame, and a point the RFP makes
twice is two cards: 67 of 382 Durham facts read almost like another. *Change
(`units.py`, model-assisted at the user's request):* a second round of small
calls, one per category with at least four facts, over the finished facts with
no document attached. The model answers `SAME|numbers` (one point, stated more
than once) or `LIST|title|numbers` (items of one list). Code keeps a fact in
the first group that names it and turns a "same" group whose members differ in
numbers or dates into a list, so no fact hides behind another. Groups are
stored on the facts and only change presentation.

Durham with grouping: 379 facts shown as 280 items; 16 groups (15 lists, 1
same) holding 115 facts; the round took 11 s of 49 s and about 5k of 56k output
tokens; recall by source ID 0.979, unchanged. The first round alone took 38 s
in this run and 21 to 47 s across today's runs, so total time is now about the
earlier pipeline's (35 to 59 s), not below it.

### Incomplete answers counted as successes (2026-11-18)

`_Run.call` in `units.py` knew two failures: an error or timeout (one retry) and
the token cap ("partial"). A call where the model simply stopped, or wrote its
own notes instead of labels, was neither, so it was logged as ok and the parser
kept whatever lines it could read. In the stored Durham run `6dad6d` the
warm-up call `LABEL1#1` answered 12 of its 74 units ("No brackets. flags. p1.3
dates issue and due; D..."), so 74 units were decided on two votes instead of
three, with 0 failed and 0 cut calls in the report. With `--votes 1` those
units would have been lost.

*Change:* a Label or State call reports how many of its units the answer
covers. An answer covering fewer than it was given is sent once more; the
answer covering more units is kept; a call still short is recorded with status
`incomplete` and listed in the report (`incomplete_calls`, `retried_calls`) and
on the Run report tab. If the retry fails or is cut, the first answer's lines
are kept. A missing END line with every unit answered is logged and not
retried: on the first run with the fix, two statement calls did exactly that,
and retrying them cost about ten seconds for the same answer.

*Durham after the fix (`2d0dc1`):* missing label votes 74 -> 2; one label call
answered 44 of 70 units, then 68 of 70 on the retry, and is listed as
incomplete; two calls were retried for missing units. Facts with three equal
votes 265 -> 302 of about 380. Recall by source ID 0.979 (unchanged), under
the reference code 0.895. 45.8 s, of which the retries of the two statement
calls that only lacked END are no longer made.

### Summary screen: summaries, not fact lists (2026-11-18)

The Summary first listed facts by category, then (at the user's request) had
five named sections that still listed facts: 37 lines under submission. A
summary screen should summarise. *Change (`units.py`, `SECTIONS`):* in the
second round, with the groups, the model writes one summary per section from
that section's facts only: buyer (B), submission (S, D), gates (G, X), scoring
(E), clarifications (Q and facts flagged unclear). Each summary has fixed rows
(for example Deadline, How to submit, Format, What to include, Required forms,
Questions), always the same and in the same order. Each row cites fact
numbers; code keeps a row only when it cites facts and every number in it is in
them, and the screen shows the cited facts for a row that fails (it caught
"3,000 employees" against 2,903 in the first buyer brief). The calendar stays
a table sorted in code: dates are not paraphrased. The facts behind each
section are folded under it. Stored in `report["summaries"]`; five calls, 5.5 s
on Durham when run alone, and part of the second round in a new extraction.


### Reference lists from goldset, and a DeepEval suite (2026-11-20)

Nothing here changes extraction. It changes how the yardstick is made and
how it is read. Not run against the live API (see "Open").

**Why reference lists are built by goldset.** Every score in this file rests on
a reference list, and each list was drafted by hand or by a subagent
(`poc/gold/`, `poc/durham/gold/`). Hand-drafting was the cost: a new RFP got no
number until someone had written about 200 to 500 lines. `src/goldset/` builds
checked cases for a prompt over a source, and `golden.py` points it at a tagged
RFP, one prompt per category, one unit per case. A worker writes the line with
verbatim quotes as evidence; code and a gate check it; what fails is corrected
or handed to a human (`needs_human.jsonl`). The extractor's own category
definitions, fact rules and flag tests are read into the prompts and not
changed, and `mandatory` / `desirable` are set by code from the unit's wording,
as in the extractor.

**Why goldset was copied in, not kept as a dependency.** The owner wants one
reference project. The copy is `src/goldset/` at commit `c172c6c` of the sibling
repo `golden-data-set-builder`, with its tests in `tests/goldset_builder/`, its
examples in `examples/goldset/` and its settings in `goldset.yaml`. Its
dependencies sit in an optional `evals` extra, so the core stays `pymupdf` and
`openai`. `golden.py` imports goldset inside its functions, so it loads without
the extra.

**Why the list is a sample, and what that does to recall.** goldset writes a
budgeted number of cases per category (default 30, `--cases`) and its planner
chooses which units to cover. The list is a checked sample, not every fact in
the RFP. `score` against it is recall on that sample: a valid yardstick for
comparing two runs, but 0.95 on it does not mean 95% of the RFP's facts were
found. The hand-written lists were written to cover the whole RFP, so figures
from the two kinds of list must not be set side by side. goldset's coverage figure is the share of the document's page and
section chunks that a checked case touches, not a fact count.

**Why Q is left out.** A contradiction cites two places. Its case needs two
unit IDs in and one line out, and the prompts and `to_gold` are built for one
unit in and a line whose main ID is that unit. `--codes` takes `BCGXDSER`.
Contradiction recall is still scored against hand-written lines.

**Why DeepEval sits on top of `score.py`.** `evalsuite.py` turns the existing
questions into DeepEval cases and metrics (a per-fact pass or fail with a
reason). `ReferenceFound` calls `score.score` for each reference fact, so it
cannot disagree with `fact-extractor score`; a second implementation of
matching would be a second thing to keep in step. Measured on the Ulster
contract list (`poc/gold/gold_c.txt`, 88 facts) against the stored `stable`
run: `deepeval test run` passed 80, `score` reports 80 under the same code (83
found). The model-judged metrics (`same_fact`, `supported`, `useful`) restate
the `judge.py` and `precision.py` questions; they replace neither. Telemetry is
opted out in `evals/conftest.py` and `.env.example`; `evals/` is not collected
by `uv run pytest`.

**Open.**

- **No live run.** `fact-extractor golden` has not been run, goldset has only
  run on a scripted model, and the judged DeepEval metrics have not called the
  API. Cost (about 160 to 200 calls per category on a 30-page RFP, roughly
  1,300 to 1,600 for eight) comes from reading the code, not from a run.
- **Thresholds are untested defaults:** 0.5 for `same_fact` and `useful`, 1.0
  for `supported`, `--cases 30`, and goldset's gate (0.85 accept, 0.25 reject).
- **The judged metrics are not checked against the hand labels**
  (`poc/ablation/labels/*.csv`). The model grades a model's output, the same
  risk as `precision --grade`; check agreement before trusting them.
- **Two copies of goldset will drift** unless the sibling repo is retired. Until
  then, a fix made in one is not in the other.
