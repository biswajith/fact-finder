# Review: RFP fact extraction spec (v1, 2 Nov 2026)

The core design is sound: tag every unit with an ID, cache the whole tagged
document as a shared prefix, split the *work* (not the document) across
parallel calls, have the model emit short pipe lines with IDs, and let code
build the citation. That attacks the real cost (output tokens) and removes
misquoting by construction. The issues below are things that would bite in
implementation or quietly cost recall/precision. Each one lists the decision
taken in this codebase.

## Must fix (spec contradicts itself or would break)

1. **Dedupe rule 8.1 destroys split requirements.** 10.5 says "If one sentence
   holds several separate requirements, write one line for each" — those lines
   share CODE and IDs. 8.1 rule 1 ("same CODE and same IDs are one fact, keep
   the longer text") then merges them back into one and drops the others.
   *Decision:* same CODE + same IDs merges only when text similarity is also
   high (≥ 0.6). Identical-ID facts with different content are kept.

2. **"Split the page range in half" has no meaning for calls A, B, C** (section
   11, output cut off). They cover the whole document. *Decision:* a cut A/B/C
   call is rerun as one call per allowed category (A → B-only and C-only, etc.).
   If a single-category call is still cut, its valid lines are kept and the call
   is marked `partial` so the run report shows it. R calls split their range as
   specified; a one-page range that is still cut is marked `partial`.

3. **Number check 7.3 fails correct facts.** The output rules ask the model to
   *reformat* (dates as YYYY-MM-DD) while the check wants every number to
   "appear in the cited text". "5 PM" vs "5:00 PM", "March 3, 2027" vs
   "2027-03-03", "$1,200,000" vs "1200000", "$1.2 million" all need
   normalisation, not just "dates and number formats". *Decision:* both sides
   are reduced to a canonical token set (ISO dates, 24h times, plain decimals
   with scale words applied, ordinals stripped). The cited text set also
   includes the section heading of each cited ID, so "Section 4.2" in a fact
   passes when the cited sentence sits under heading 4.2.

4. **Message order 5.2 vs prompts 10.6/10.7.** The sweep and check prompts put
   large variable content (`{{uncited_ids}}`, `{{merged_fact_lines}}`) in the
   task message. That is fine for caching (it is after the document) — but the
   spec also says the check call uses *medium* effort. Reasoning effort is a
   request parameter, not prefix bytes, so this does not break the cache.
   Worth stating explicitly so nobody "fixes" it by moving effort into a
   prompt. No change, documented in `prompts.py`.

5. **Escaping.** If RFP text itself contains `[p3.1]`-style brackets or a line
   starting with `[`, the tagged document becomes ambiguous and the model can
   cite a fake ID that then *exists in text but not the map*. Also, table cells
   are joined with ` | ` (4.2 example) while `|` is the output separator, so
   the model is primed to copy `|` into facts. *Decision:* square brackets in
   source text are rendered as `(`…`)`, and table cells are joined with ` ; `
   in the tagged text. Anchor-map `text` keeps the original.

## Should fix (gaps, ambiguity)

6. **END count semantics.** Is `END|n` the count of fact lines including Q
   lines? For the sweep, including NONE lines? *Decision:* every non-END line.
   A count mismatch with an END present is logged but does not trigger a rerun
   (the output was not cut); only a missing END does.

7. **Section-aware ranges (5.1) vs page ranges (10.5).** Sections start
   mid-page, ranges are whole pages. *Decision:* a page belongs to the section
   of its first candidate; a "section block" is the run of pages whose first
   candidate is in that section. Blocks are packed greedily to ~40 candidates;
   a block with ≥ 60 candidates is split by page.

8. **"will" as a candidate word** flags lots of buyer statements ("The County
   will award…"). That inflates R-call sizing and the sweep list. Kept as
   specified for recall, but the sweep handles it cheaply via `NONE|no fact`.
   Worth measuring on the gold set.

9. **Coverage is "cited by any fact".** A "must" sentence cited only by a D or
   S fact is treated as covered and never becomes an R fact. That is likely
   the intended trade-off but should be explicit. *Decision:* configurable;
   default follows the spec.

10. **Sweep output validation.** The sweep's contract is "every listed ID in
    exactly one line". *Decision:* IDs missing from the sweep output are
    reported in the run log; NONE lines are validated for ID existence only.

11. **Q lines from every call** will repeat the same contradiction from
    several calls. *Decision:* Q lines go through the same dedupe, then into
    the check call's fact list, so the check can confirm/extend them.

12. **Wall time is sequential in three stages** (extract ~17 s → sweep ~5 s →
    check ~25 s). Total in the table is right but has no slack against the
    60 s target once a cut-off rerun happens. *Option (not default):* run the
    check on the pre-sweep facts in parallel with the sweep. The sweep adds few
    facts, so contradictions involving only sweep facts are rare. Exposed as
    `parallel_check=True`.

13. **Cache warm-up (5.2)** "start the others when the first begins to stream"
    — the cache entry is written when the prefix is processed, which is before
    the first output token, so waiting for the first streamed token is the
    right signal. Implemented exactly that way, with a timeout fallback so a
    slow first call does not serialise the run.

14. **Store identity.** `fact_id` format is unspecified; re-running a document
    should not duplicate facts. *Decision:* `fact_id` = hash of
    (doc_id, category, main cited ID, counter for repeats); store keyed by
    (deal_id, doc_id, run_id). Until 2026-11-18 the hash used the sorted IDs
    and the normalised text, which changed on nine facts in ten between two
    runs (see "Run-to-run stability"). Storage here is in-memory (per request).

15. **Status `conflict`** is listed but never assigned by any step.
    *Decision:* facts cited by any Q line from the check get status
    `conflict` (and keep the Q line ID in a `conflicts` field).

16. **Multi-page sentences / tables.** A sentence that runs over a page break
    gets the ID of the page where it starts; a table continued on the next
    page restarts row numbering on the new page (IDs stay page-local) and
    reuses the header from the previous page if the new fragment has none.

17. **The sweep can be bigger than any extraction call.** One line per uncited
    ID, ~30 tokens each: 200 uncited candidates (easy with "will" counted) is
    ~6,000 tokens, over the 3,000 cap. The sweep gets cut, and section 11 has no
    rule for it. *Decision:* the sweep goes out in parallel chunks of 60 IDs, and
    a cut sweep chunk is halved like an R range.

18. *(Repair removed 2026-11-16, see "Trimming tests"; failed lines are now kept
    as `needs_review` without a repair call.)* **Repair `DROP` vs "do not drop it".** Prompt 10.8 lets the model answer
    `DROP`, but section 7 says a line that fails twice is kept as
    `needs_review`. *Decision:* a DROP keeps the original line as
    `needs_review` with the drop reason in `problems`. Nothing the model wrote
    is lost silently.

## Minor

- "Keep numbers and units as in the source" (6.1) vs "Dates as YYYY-MM-DD" —
  dates are the one exception; say so.
- Rule "Split very long sentences at semicolons only if longer than 60 words"
  — the split parts get consecutive IDs; that is how it is implemented.
- Decisions API and OpenEvals are external; here the Decisions hand-off is a
  pluggable callback and a stub is provided.

## Open questions in section 14

Agree with the list. For very large tables, storing the table as an object
and citing it once is the better default: one R fact per row would dominate
the output budget of a call (a 300-row pricing sheet ≈ 9,000 tokens ≈ 75 s).

## Bid manager tailoring (changes to the spec's prompts)

The harness runs for a bid manager, who decides bid/no-bid, builds the
compliance matrix and submission checklist, and must spot contract risk. The
spec's prompts aim at a generic "sales team". Changes:

- **New category E, evaluation criteria**, written by call A with buyer facts: each
  criterion with points or weight, screening, price scoring, interviews. The
  spec had no place for how proposals are scored; the first POC run on the
  Ulster County RFP lost its "5.0 EVALUATION CRITERIA" section (35/30/... points)
  across G, X and R. The E call also writes a Q line when weights do not add up.
- **Flags in the note field**: `mandatory`, `desirable` (R lines), `risk`
  (unusual contract terms in C), `unclear` (questions to ask the buyer),
  `replaced`. Stored as a `flags` list on each fact; free text stays in `note`.
- **System prompt**: audience is the bid manager; facts must be specific and
  actionable; never a `|` between an event and its date; END never gets a code
  in front (both seen in the POC run).
- **G tightened**: only conditions that decide whether the bidder may bid or
  win. Process rules (addenda, interpretations) were filling G in the POC.
- **D**: relative deadlines ("within 10 days of award") are D facts, and the
  form is "event: date".
- **S**: one fact per required form, so S works as a submission checklist.
- **R**: questions the proposal must answer ("describe", "indicate") are
  requirements; candidate words for the sweep gain should, describe, provide,
  indicate, submit, include.
- **Check prompt**: also looks for points that do not add up and RFP terms that
  differ from the sample contract.
- **Contract terms (C) get their own calls `K1`, `K2`** (one per half of the
  document's text; three calls `K1` to `K3` since 2026-11-18, see "Run-to-run
  stability"), and a cut one-category call now splits by pages, and standard legal text with
  no amount, deadline, action or risk is skipped. With one-fact-per-clause, C
  alone wrote 150+ facts and hit the 3,000-token cap twice in one run (93 s).
- **Check alongside the sweep by default** (`--sequential-check` turns it off):
  the 20 s check no longer waits for the sweep. Sweep facts are not checked for
  contradictions; on the POC the sweep added few facts. Sweep chunks are 30 IDs.
- **Parallelism default 16**: every extraction call of a ~50-page RFP runs at
  once; at 8, four R calls queued for 7–10 s in the POC.

### Changes after the reference comparison

A reference list (580 facts, written by three independent subagents in
`poc/gold/`) scored the tailored run with `fact-extractor compare`: 90.5% of
reference facts found under some code, but only 35% of disqualifiers and 59% of
buyer facts. Fixes:

- **X** now requires a stated consequence (rejected, disqualified, not opened,
  not considered). Submission rules with no consequence are S. The run had put
  copies, labels and title pages in X and missed "failure to provide insurance
  shall disqualify".
- **B** names the background a bid team prices from (headcounts, volumes, claim
  counts) and every contact, one fact each. The "skip text with nothing to act
  on" rule had removed them; it now reads "nothing to know, do, or decide".
- **Q lines on the same IDs merge** in dedupe whatever their wording.
- **Check prompt** also looks for references to blank or missing sections and
  for two as-of dates for the same data (both missed in the run).

**Matcher fix (2026-11-11).** The scores above, and in `poc/compare_run*.json`,
came from a lenient matcher: one extracted fact could count for several gold
facts (run 9: 555 matches from 425 facts, one used 7 times), the category and
citation bonuses could carry a match with almost no shared words, and overlap
was measured against the shorter text, so short vague facts scored high. Now
matching is one-to-one (best pairs first), bonuses only break ties, and text
similarity must reach 0.4 measured against the gold fact's words. Run 9 drops
from 95.7% to 72.1% found under some code; 89 of the new misses are gold facts
folded into an extracted fact already matched elsewhere (column `merged`).

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

### Cross-reference check (code)

`xref.py` reads every "Article N (Title)", "Section N", "Schedule X",
"Attachment X" reference and looks it up in the document's own headings. It
writes a Q fact (source `XREF`) when the target is blank or reserved, has a
different title, or, for articles, does not exist. References into other laws
("Article 15 of the Executive Law") are skipped, and missing attachments are
not reported, since they are often separate files.

Why code: the model's check missed "Article 17 (Intellectual Property)" in the
survival clause vs "ARTICLE 17 – INTENTIONALLY LEFT BLANK" six pages earlier.
Neither side was a fact (the heading carries no action; the clause was
summarised without its article list), and the sweep fact that cited the clause
is not seen by the check when it runs alongside the sweep. The code check costs
no model call, runs after the merge, and dedupes with any model Q line on the
same IDs. On the Ulster County RFP it reports exactly this one mismatch across
49 headings; with it, every reference contradiction is found.

### Recall options (two passes, wide sweep)

Scored against the 580-fact reference list (`fact-extractor compare`):

| Run | Facts | Reference facts found | Missed |
| --- | --- | --- | --- |
| 1 pass, sweep of shall/must sentences | 569 | 94.0% | 35 |
| 1 pass, sweep of every uncited sentence | 632 | 95.7% | 25 |
| 2 passes merged, sweep of every uncited sentence | 721 | 98.6% | 8 |
| Same, rerun at normal API speed (2026-11-02 23:07) | 701 | 99.3% | 4 |

- **Two passes** (`passes=2`; default until 2026-11-16, now 1, see "Trimming tests"): every extraction call runs twice and the
  passes are merged one-to-one (`merge.union_passes`): a second-pass fact merges
  with at most one first-pass fact (same code, shared ID, similar wording);
  facts within a pass never merge, so split requirements survive. About 2% of
  the merged facts are still near-duplicates. Costs twice the extraction tokens.
- **Wide sweep** (`sweep_all=True`, default): the coverage sweep covers every
  uncited sentence, row or heading with three or more words (766 of 849 IDs on
  the POC RFP), not only the 333 shall/must candidates.
- The 1-pass misses were mostly the non-collusion affidavit's certifications,
  insurance options and office contacts; the second pass found them.
- **Check budget**: the medium-effort check spent all 3,000 tokens on hidden
  reasoning over a 700-fact list and wrote nothing. It now gets 8,000.
- **Time**: not measured fairly. During both runs the API was slow for every
  call (time to first token 45 to 75 s, against 4 to 8 s earlier the same day,
  and two 120 s timeouts), so 237 s and 333 s say nothing about the design. At
  normal API speed the second pass adds no stage (calls run in parallel), but it
  doubles concurrent requests (30), which may meet account limits. CLI:
  `--passes 1` and `--narrow-sweep` trade recall for time.
- **Time at normal API speed** (rerun, 2026-11-02 23:07): 72.7 s in the
  pipeline (extract 35.6 s, sweep and check 37.1 s), plus 14 s of PDF tagging
  before it. 47 calls, no failures, no retries, no 429s; cache hit 32%.
  Time to first token p50 6.4 s, p95 8.8 s at 30 concurrent calls, against 4 to
  6 s at 15 to 24 earlier: slightly higher, but not what sets the total.
  Tokens/s p50 91, p95 105. The total is set by two long calls: the slowest
  extraction call (C#2, 26 s, 2,885 output tokens) and the check (34 s, of which
  31 s is hidden reasoning before the first token, over a 700-fact list). To get
  under 60 s, the check is the target (lower effort, or check by category on
  smaller lists), and tagging (14 s, mostly table detection) is the second.

### Trimming tests (2026-11-16)

`poc/ablation/run.sh` ran seven configurations on both RFPs; `score.sh` scores
recall (`compare --judge`) and precision (`precision --grade`), and
`summarize.py` writes `poc/ablation/summary.json`. Durham recall is against
`poc/durham/gold/gold_draft.txt` (238 facts, written by a subagent that never
saw any extractor output; **not yet checked by a person**).

| Config | Ulster recall | Durham* recall | Ulster out tokens | Ulster s |
| --- | --- | --- | --- | --- |
| base (2 passes, wide sweep) | 0.910 / 0.946 (rerun) | 0.979 / 0.979 | 56-58k | 63-69 |
| 1 pass | 0.916 | 0.950 | 36k | 48 |
| 1 pass, narrow sweep | 0.869 | 0.912 | 26k | 44 |
| 1 pass, no sweep | 0.829 | 0.853 | 24k | 55 |
| 1 pass, no repair | 0.923 | 0.966 | 34k | 46 |
| 1 pass, cap 8,000 | 0.919 | 0.971 | 34k | 46 |

- **Run-to-run noise is about 3.5 points** on Ulster (base vs rerun, same config).
- **The wide sweep earns its place**: without it recall drops 9-12 points;
  the narrow sweep drops 4-5.
- **The second pass adds 0-3 points**, within noise on Ulster, for ~60% more
  output tokens and ~15-20 s.
- **Repair adds nothing measurable**; without it 3-6 facts per run stay
  `needs_review`.
- **The output cap does not matter**: at most one cut call per run at 3,000.
- **Precision (model-graded)**: 89-92% of facts fully supported, ~8% partly
  (a dropped condition or overstatement), ~2% not supported, including a
  reversed party ("Give County five days" where the source gives the
  responder five days). The grader marks almost nothing as noise (0.4%), so
  its usefulness verdict is not trustworthy until checked against labels in
  `poc/ablation/labels/`. The near-duplicate count is rough: most pairs it
  finds on Durham are sibling facts, not restatements.

**Defaults changed after these tests (2026-11-16):** `passes` is now 1, and the
repair call and its prompt are removed; lines that fail validation are kept as
`needs_review`. The wide sweep stays on.
Two Ulster runs with the new defaults: 0.882 and 0.908 found (47-48 s, 34k
output tokens, 7-10 `needs_review`). Over the four one-pass Ulster runs the
mean is ~0.907, against ~0.928 for the two two-pass runs: about 2 points, at
the edge of run-to-run noise. Use `--passes 2` when those points matter more
than the extra cost.

### Run-to-run stability (2026-11-18)

Two runs of one configuration on one RFP give different fact lists. The code is
not the source: tagging the same PDF twice gives the same bytes, the call plan
is fixed, and nothing in the pipeline is random. The request sets no
temperature or seed (`llm.py`) and extraction runs at low reasoning effort, so
every call is a fresh sample. Measured on the two Ulster runs with the
2026-11-16 defaults (`poc/ablation/after_change/ulster`, `ulster_rerun`):

| Measure | Run A | Run B | Shared |
| --- | --- | --- | --- |
| Facts | 640 | 656 | 57 with the same `fact_id` |
| Source IDs cited | 623 | 617 | 582 |
| IDs filed under the same set of codes | | | 320 of 582 |
| Sweep facts | 145 | 117 | |
| Sweep facts coded X / S | 35 / 18 | 0 / 1 | |
| Reference facts missed (of 467) | 55 | 43 | 19 |

The model finds nearly the same sentences each time. It files, groups and
words them differently, and the pipeline passed each difference on:

- **No call knew the category boundaries.** A task carried the definitions of
  its own codes only, and R overlaps C, S and G. One sentence was picked up by
  one, two or three calls depending on the run; dedupe compared facts within
  one code only, so the copies stayed.
- **The sweep had no definitions at all**, only the nine letters, and wrote a
  fifth of the facts. "The County may reject any or all proposals" was X in one
  run and G in the next.
- **The sweep's input is what extraction left uncited**, which differs per run;
  for IDs swept in both runs, fact-or-NONE flipped on 38 of 250.
- **`fact_id` hashed the wording.**
- **`K2` sat at the output cap** (2,300-3,000 of 3,000 tokens), so whether it
  was cut and split changed between runs.
- **The scorer adds its own noise.** 44 of run A's 55 misses have their source
  sentence cited by some fact of that run: the fact was grouped or worded so
  it did not pair with the reference line. The judge is a model call too: of
  125 Ulster pairs judged in more than one run, 16 got a different verdict.
  The gap between the two runs is 1.7 points on wording alone and 2.6 with the
  judge.

*Changes, all departures from the spec's prompts and section 8:*

1. **The system prompt defines all nine categories and an order for ties**
   (rule 13: X, G, D, S, E, C, R, B; skip a statement whose code belongs to
   another call). A task still repeats the definitions of its own codes. The
   prefix is still the same bytes in every call (~1,450 tokens, was ~500).
   Rule 10 now says one line per separate item, where it used to say "do not
   split one fact", against the R task's "one line for each".
2. **Dedupe merges across codes**, only for a plain restatement: same main ID,
   each fact holds 80% of the other's content words, and the kept fact has
   every number and date of the dropped one. The code first in the order above
   is kept, with the flags of both. A looser rule (60% of the dropped fact's
   words) also merged second views a bid manager wants (the due date as D next
   to "late proposals are not opened" as X) and cost about 2 points of recall.
3. **`fact_id` no longer depends on wording** (item 14).
4. **Three contract calls** (`K1` to `K3`) in place of two.
5. **`fact-extractor stability a.json b.json`** reports agreement on cited IDs,
   codes per ID and fact IDs. `score.sh` gives all runs of a document one judge
   cache (`poc/ablation/judge.<doc>.json`, seeded from the verdicts of the
   earlier runs).

*Measured by replaying changes 2 and 3 over the saved facts (no model call):*

| Run pair | Facts | Shared `fact_id` before | after | Recall on wording, before | after |
| --- | --- | --- | --- | --- | --- |
| Ulster, 1 pass | 640, 656 -> 615, 627 | 57 | 367 | 0.820, 0.837 | 0.818, 0.833 |
| Durham, 2 passes | 462, 488 -> 428, 463 | 64 | 315 | 0.954, 0.941 | 0.950, 0.941 |

About 25 cross-code restatements go per run, nearly all R copies of a C, S or
G fact, for one or two reference facts that then pair with nothing.

*Measured with all five changes* (2026-11-18, two runs per RFP, one pass,
`poc/ablation/stable` and `stable_rerun`, scored with the shared judge cache):

| | Ulster before | Ulster after | Durham before | Durham after |
| --- | --- | --- | --- | --- |
| Facts | 640, 656 | 564, 615 | 424 | 385, 422 |
| Recall, any code | 0.882, 0.908 | 0.872, 0.895 | 0.950 | 0.937, 0.950 |
| Recall, same code | 0.704, 0.747 | 0.741, 0.775 | 0.786 | 0.836, 0.819 |
| Cited-ID agreement | 0.884 | 0.915 | 0.958 (2 passes) | 0.901 |
| Code agreement per ID | 0.55 | 0.73 | 0.69 (2 passes) | 0.82 |
| `fact_id` agreement | 0.05 | 0.56 | 0.07 (2 passes) | 0.67 |
| Output tokens | 34-35k | 35-37k | 25k | 23-24k |

"Before" is the 2026-11-16 defaults; Durham had one one-pass run, so its
agreement figures come from the two-pass pair.

- **Filing is steadier**: two runs now agree on the codes of 73% (Ulster) and
  82% (Durham) of the sentences both cite, and more reference facts are found
  under their own code.
- **Recall is about one point lower on Ulster** (mean 0.884 against 0.895 for
  the pair before, 0.907 over all four earlier one-pass runs) and unchanged on
  Durham. Two runs cannot separate one point from noise; the likely cause is
  rule 13 (a call skips a statement it thinks belongs to another call) and the
  ~25 merged restatements.
- **What still varies is how much the R calls write**: 246 against 292 R facts
  on Ulster, and the commonest difference is a sentence one run files as R and
  the other does not cite under R at all (49 IDs). Dates swing too (16 against
  31 D facts on Ulster).
- **The third contract call did not take `K` off the cap on Ulster**: the
  ranges hold equal text, but contract facts are not spread evenly: `K2`
  (pages 18-26) wrote 66-69 lines and up to 2,884 of 3,000 tokens, `K1` 12-19
  lines.
  No call was cut in these four runs.
- The first run after a prompt change reads nothing from the cache (hit rate
  0.04-0.06); the second is back at 0.54-0.58, as before.

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
3. **The UI has a View switch** on Summary and Facts: *Bid* hides `post-award`
   facts unless they have the `risk` flag or state an amount (these are listed
   as "After award, but price or decide it now"); *After award* shows only
   `post-award` facts. Runs made before the flag show everything under Bid.

*Measured* (two runs per RFP, `poc/ablation/award` and `award_rerun`):

| | Ulster | Durham |
| --- | --- | --- |
| Recall, any code | 0.889, 0.884 (was 0.872, 0.895) | 0.941, 0.962 (was 0.937, 0.950) |
| Code agreement per ID | 0.73 (was 0.73) | 0.79 (was 0.82) |
| G facts | 6, 6 (was 14, 12) | 3, 3 (was 15, 12) |
| Facts flagged `post-award` | 273, 248 | 26, 48 |
| Sentences flagged in both runs, of those flagged in either | 157 of 196 | 13 of 48 |

- Recall did not move. The Durham insurance facts are now all C with
  `post-award`, and the three Durham gates left are real ones (state law,
  Oracle-approved partner, similar past projects).
- **The flag is steady on contract terms and not on requirements.** On Ulster,
  with a long sample contract, two runs agree on 80% of the flagged sentences.
  On Durham one run flagged 1 R fact and the other 32: a statement-of-work
  item is both something the proposal must describe and something the winner
  must deliver, and the rule does not say which wins. Until it does, read the
  After award view as reliable for C facts and as a rough guide for R facts.
- Still open: a rule for R facts (for example: flag an R fact `post-award`
  only when the RFP asks for no response to it in the proposal), and whether
  the bid view should use an explicit "price this" flag instead of looking for
  an amount in the text.

### General principles, not point fixes (2026-11-18)

The post-award rule was first patched case by case: an insurance example in the
G definition, a clause for R facts in the rule, a paragraph in the requirements
task. Each patch fixed the RFP it was written for and moved the variation
elsewhere: the R clause made two Durham runs agree (2 of 2 flagged
requirements) and two Ulster runs disagree (48 of 96, from 61 of 81). The
patches were removed and the prompt rebuilt from statements that hold for any
RFP. Tested on Durham only, two runs per version.

*What the system prompt now says, in this order:*

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

*What tasks say:* their codes, the definitions of those codes, where to look,
and one closing line that is the same in every task ("check each flag against
its test, line by line"). No task restates or adds to a flag.

*What each general change did (Durham, pairs of runs):*

| Version | Facts | Recall | S facts | Code agreement | Post-award agreement |
| --- | --- | --- | --- | --- | --- |
| Patched rule (`award_v3`) | 429, 452 | 0.966, 0.954 | 28, 97 | 0.61 | 23 of 23 |
| Principles (`general`) | 378, 379 | 0.933, 0.941 | 29, 40 | 0.79 | 20 of 46 |
| + same closing line in every task (`general_v2`) | 356, 429 | 0.945, 0.975 | 28, 97 | 0.58 | 43 of 52 |
| + S and R defined apart (`general_v3`) | 335, 365 | 0.937, 0.945 | 21, 21 | 0.74 | 30 of 48 |

- **"A fact is a point, not a sentence" removed the page-8 duplicate**: three
  sentences on disqualification for insufficient understanding gave three X
  facts before, and one fact citing all of them in four of the six runs that
  followed. The other two wrote two and three facts over the same sentences,
  so the principle helps and does not settle it.
- **Flags in the system prompt alone were applied all-or-nothing per call**
  (the contract calls flagged every insurance term in one run and none in the
  next). One identical reminder at the end of every task brought agreement on
  post-award from 20 of 46 to 43 of 52; the next pair, with the same reminder,
  gave 30 of 48. Insurance terms were post-award in all four runs with the
  reminder; what still flips is mostly requirements.
- **The largest swing in facts and codes was one overlap between two
  definitions.** S ("every required form... section order") and R ("each item
  the proposal must answer") both claimed proposal content, so the D/S call
  wrote about 30 S facts in one run and about 100 in the next, hit the output
  cap and split. The patched version had it too (28 and 97). With S
  defined as the package and R as the content, S is 21 and 21 and no call
  split.
- **Recall is 1 to 2 points under the patched version** (0.94 against 0.96)
  with about 80 fewer facts per run. The reference list is a draft and counts
  S copies of R facts as found, so part of this is the measurement.

*Limits of this evidence:* two runs per version, one RFP. Code agreement moved
between 0.58 and 0.82 across pairs that differ little, so a single pair cannot
rank two prompts on it, and the same holds for post-award agreement (43 of 52
and 30 of 48 under one prompt). Only the S count moved by clearly more than
its own noise. Ulster has not been run with the
general prompt.

### A fact is a labelled source unit: trial (2026-11-18)

The pipeline asks the model to write facts, so the model decides which
sentences to use, how to group them, the code and the wording, and no two runs
give the same list. Over 14 Durham runs, of 578 tagged units 315 were used by
every run, 119 by none and 144 by some. The reference list has one fact per
main ID for 219 of its 227 main IDs.

Trial (`poc/unit_trial/trial.py`, Durham only, nothing in `src/` changed): the
model writes no facts. For every unit it gives a label (a code, `=` for a
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
