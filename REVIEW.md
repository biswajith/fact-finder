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
    (doc_id, category, sorted IDs, normalised text); store keyed by
    (deal_id, doc_id, run_id). Storage here is in-memory (per request).

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

18. **Repair `DROP` vs "do not drop it".** Prompt 10.8 lets the model answer
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
  document's text), and a cut one-category call now splits by pages, and standard legal text with
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

- **Two passes** (`passes=2`, default): every extraction call runs twice and the
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
