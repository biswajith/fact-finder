# UI spec: fact review app

Status: reviewed, ready to build, 2026-11-18. Library: Streamlit.

## 1. Purpose

A bid manager reads the facts of one extraction run, checks any fact against the
RFP page it came from, and takes the lists they act on (dates, gates,
disqualifiers, submission checklist, compliance matrix) out as CSV. An engineer
uses the same app to look at a run's report and to see how far two runs agree.

The app reads what `fact-extractor extract` already writes. It does not change
the pipeline, the prompts or the output format.

## 2. Scope

In version 1:

1. Open a saved run (a `facts.json`, its `report.json` if present, and the PDF).
2. Summary of the run for a bid manager.
3. Browse, filter and search facts; see each fact's source highlighted on the
   PDF page.
4. Download the filtered facts as CSV.
5. Run report for an engineer.
6. Compare two runs (`stability.compare_runs`).
7. Start a new extraction from the app, behind an explicit confirmation.

Not in version 1: editing or approving facts, user accounts, a database,
scoring against a reference list (`compare`, `precision`), scanned PDFs,
deployment anywhere but the user's own machine.

## 3. Why Streamlit

- One Python file per page, no HTML, CSS or JavaScript to write.
- Built-in table with row selection, file upload, download button, tabs,
  sidebar and image display cover every screen below.
- The app is single-user and local, so Streamlit's rerun-the-script model and
  lack of routing or auth cost nothing here.

Gradio is built around one input-to-output function and is awkward for a
table-plus-detail layout. NiceGUI and Reflex can do more but need more code for
the same screens.

## 4. Data the app reads

All of it exists today.

**Fact record** (one element of `facts.json`):

```json
{
  "fact_id": "f_65ed2f51cf", "deal_id": "ulster", "doc_id": "rfp-uc26-039",
  "run_id": "run_2026_11_16_916fe5", "category": "B",
  "text": "Buying organization is County of Ulster, Department of General Services",
  "citations": [
    {"id": "p1.h1", "page": 1, "page_label": "1", "section": "COUNTY OF ULSTER",
     "text": "COUNTY OF ULSTER", "bbox": [173.0, 76.6, 445.3, 112.4]}
  ],
  "unresolved_ids": [], "flags": [], "note": "", "status": "valid",
  "source_call": "A", "problems": [], "conflicts": []
}
```

- `category`: one of B, C, G, X, D, S, E, R, Q. Names are in
  `fact_extractor.models.CATEGORIES`.
- `status`: `valid`, `needs_review` or `conflict`.
- `flags`: any of `mandatory`, `desirable`, `risk`, `unclear`, `replaced`,
  `post-award`. Added after the first build: Summary and Facts have a View
  switch (All, Bid, After award). Bid hides `post-award` facts unless they have
  the `risk` flag or state an amount; After award shows only `post-award` facts.
- `citations[].page` is the 1-based page of the PDF file; `page_label` is the
  number printed on the page and may differ. `bbox` is `[x0, y0, x1, y1]` in
  PDF points with the origin at the top left, as PyMuPDF reports it; it can be
  `null`.
- `conflicts` holds the `fact_id`s of Q facts that cite the same source.
- `problems` holds the reasons a fact is `needs_review`.

**Run report** (`report.json`): `run_id`, `doc_id`, `pages`, `ids`, `facts`,
`by_category`, `by_status`, `seconds` (per stage and `total`), `output_tokens`,
`cache_hit_calls_2_to_n`, `failed_calls`, `performance`, and `calls` (one entry
per model call with `name`, `kind`, `status`, `seconds`, `lines`, `retries`,
`log`, `usage`, `output`).

**Sample data for building and testing** (read only, never modify):
`poc/ablation/stable/ulster/` and `poc/ablation/stable_rerun/ulster/` (`facts.json`,
`report.json`), with the PDF
`RFP-UC26-039 ACTUARIAL SERVICES FOR ULSTER COUNTY SELF INSURANCE PLAN.pdf` in
the repository root.

## 5. Finding runs and their PDFs

A run is a facts file, optionally with a report and a PDF beside it.

- The sidebar has a "Runs folder" text field (default: the `--runs` argument,
  else `runs` if it exists, else `poc`). The app lists every `facts*.json`
  under it, recursively, newest first, labelled by path relative to the folder,
  with the fact count. The listing is cached and has a "Refresh" button.
- A file counts as a facts file only when it is a JSON list whose first element
  is an object with `category`, `text` and `citations`. Anything else is
  skipped without an error. This matters: `poc/` holds 17 `facts*.judge.json`
  files that match the name and are not facts.
- The report of `facts.json` is `report.json` in the same folder; the report of
  `facts_<name>.json` is `report_<name>.json` (`poc/facts_run1.json` and
  `poc/report_run1.json`).
- Older runs lack some fields (two files in `poc/` have no `flags`). Every
  field except `category`, `text` and `citations` is read with a default:
  empty list or empty string, `status` "valid", `fact_id` the row number.
- The PDF for a run is found in this order: `source.pdf` next to `facts.json`;
  a PDF the user picked earlier in this session for the same `doc_id`; else the
  sidebar shows a select box of the `*.pdf` files in the working directory plus
  an upload control. Without a PDF the app still works; the source panel shows
  the cited text only and says no PDF is attached.
- Runs started from the app (section 6.5) are written to
  `runs/<doc_id>/<run_id>/` with `facts.json`, `report.json` and `source.pdf`,
  so they open with their PDF. `runs/` is added to `.gitignore`. `doc_id` and
  `run_id` are used as folder names only after every character outside
  `A-Z a-z 0-9 . _ -` is replaced with `_`.

## 6. Screens

One Streamlit app with a sidebar (run picker, PDF picker) and five tabs.

### 6.1 Summary

For the bid manager, top to bottom:

- Header: `doc_id`, `run_id`, pages, number of facts.
- A row of counts: needs review, conflicts, risk flags, mandatory requirements,
  unclear items. Each count is the number of facts, computed from the records.
- **Key dates**: every D fact, as a table of text and page.
- **Go/no-go gates** (G) and **Disqualifiers** (X): text and page.
- **Contract risks**: C facts with the `risk` flag.
- **Contradictions** (Q): text and pages of both sides.
- Bar chart of facts per category, labelled with the category names.

Tables here are read-only; the Facts tab is where a fact is inspected.

### 6.2 Facts

*Changed after the first build (2026-11-18):* the grid table cut every fact off
and looked like a report tool. The screen is now a reading list: type chips with
counts above it, one card per fact with its full sentence, flags and page, 15 to
60 cards per page, and an Open button per card. The first fact is open by
default and the source panel stays in place while the list scrolls. Status,
flags, page range and page size are under "More filters". The rest of this
section describes the first build.

Two columns.

Left, filters then the table:

- Category: multiselect, labels "R - requirement" style, default all.
- Status: multiselect, default all.
- Flags: multiselect; a fact matches when it has any of the chosen flags.
- Search: case-insensitive substring over the fact text and the cited text.
- Page range: slider over 1..pages, matching a fact when any citation is on a
  page in range. `pages` comes from the report, else from the highest cited
  page.
- Count line: "N of M facts".
- Table columns: category, text, flags, status, page (page label of the first
  citation), source call. One row selectable at a time. Sorted by the page and
  position of the first citation, so the list reads in document order.
- "Download CSV" button for the filtered rows (section 7).

Right, the selected fact:

- Text, category name, status, flags, note, source call, `fact_id`.
- `problems`, when present, in a warning box.
- `conflicts`, when present: the text of each linked Q fact.
- One block per citation: ID, section, page label, and the cited text.
- The PDF page of the chosen citation (a select box when there are several,
  default the first), rendered as an image with every citation of this fact on
  that page drawn as a translucent highlight. Citations with `bbox: null` are
  listed but not drawn.
- `unresolved_ids`, when present, with a note that the model cited IDs that are
  not in the document.

With no row selected the right column says "Select a fact to see its source".

### 6.3 Run report

- Totals: seconds per stage, output tokens, cache hit rate, calls by status,
  failed calls.
- Table of calls: name, kind, status, seconds, lines, output tokens, retries.
- Selecting a call shows its `log` lines and raw `output` in a code block.
- If the run has no `report.json` the tab says so.

### 6.4 Compare runs

- Two select boxes over the listed runs. Only runs with the same `doc_id` as
  run A are offered for run B.
- Shows `stability.compare_runs(a, b)`: the three agreement figures as metrics,
  the per-category table, and the list of code differences.
- A note under the fact ID figure: runs made before 2026-11-18 hashed the
  wording into `fact_id`, so their fact ID agreement is near zero whatever the
  runs contain.
- A table of source IDs both runs cite but file under different codes: ID,
  codes in A, codes in B, and the fact texts from each.

### 6.5 New run

- Inputs: PDF (upload, or pick from `*.pdf` in the working directory), deal ID,
  doc ID (default: file name without extension), model (default from
  `FACT_EXTRACTOR_MODEL`), passes (1 or 2).
- Before starting, show the planned calls from `planner.plan_calls` (name,
  codes, page range) and a line stating that the run calls the model and spends
  tokens.
- A "Start extraction" button, enabled only after a checkbox "I understand this
  spends API tokens" is ticked, and only when `OPENAI_API_KEY` is set (after
  `cli.load_env()`); otherwise a message says which variable is missing. The
  key is never displayed.
- The run uses the same code path as the CLI (`tag_pages(read_pdf(...))`,
  `pipeline.extract` with `OpenAIClient`, called with `asyncio.run`), and writes
  the same JSON the CLI writes with `--out` and `--report`.
- While running: a spinner. On finish: the same one-line result the CLI prints
  (facts, statuses, seconds, failed calls), files written to
  `runs/<doc_id>/<run_id>/`, and the new run selected in the sidebar.
- On an exception: the error message, and nothing written.

## 7. CSV export

Columns, in order: `category`, `category_name`, `text`, `flags` (joined with
`; `), `status`, `page_labels` (distinct, joined with `; `), `sections`
(distinct, joined with `; `), `citation_ids` (joined with `; `), `source_text`
(cited texts joined with ` / `), `note`, `problems` (joined with `; `),
`fact_id`. UTF-8 with a byte order mark so Excel opens it correctly. File name:
`<doc_id>_<run_id>_facts.csv`.

## 8. Code layout

```
src/fact_extractor/ui/__init__.py
src/fact_extractor/ui/data.py     # no Streamlit import: load, filter, summarise, CSV, page image
src/fact_extractor/ui/app.py      # Streamlit only: layout and widgets, calls data.py
tests/test_ui_data.py
tests/test_ui_app.py
```

`data.py` functions (names may change, the split may not):

- `find_runs(folder) -> list[RunRef]`: path, fact count, modified time.
- `load_run(path) -> Run`: records, report or `None`, PDF path or `None`.
- `filter_facts(records, categories, statuses, flags, query, pages) -> list[dict]`
- `document_order(records) -> list[dict]`: sort by first citation page, then by
  the position encoded in the ID (`p12.4` before `p12.10`; headings `h` and
  table rows `t..r..` after plain sentences of the same number is acceptable).
- `summary(records) -> dict`: the counts and lists of section 6.1.
- `to_csv(records) -> bytes`
- `render_page(pdf_path, page, boxes, zoom=1.5) -> bytes`: PNG of the page with
  the boxes highlighted. Uses PyMuPDF only: open the file, draw on the page in
  memory (`page.draw_rect` with a fill and fill opacity), `get_pixmap`, return
  PNG bytes. The PDF on disk is never written.
- `code_differences(a, b) -> list[dict]`: rows for the table in 6.4.

`app.py` caches `load_run` and `render_page` with `st.cache_data`.

Launch:

- `fact-extractor ui [--runs FOLDER] [--port N]` starts Streamlit on `app.py`
  (a subprocess running `python -m streamlit run <app.py> -- --runs FOLDER`).
  If Streamlit is not installed it prints the install command and exits 1.
- Streamlit is an optional dependency: `[project.optional-dependencies]`
  `ui = ["streamlit>=1.40"]`, installed with `uv sync --extra ui`. The core
  package and its tests must import and pass without it.

## 9. Behaviour rules

- The app never writes outside `runs/` and never modifies a run it opened.
- No model call happens except through the confirmed button in 6.5.
- Changing a filter or the run clears the selected fact. (Streamlit keeps a
  table selection by row number, so a kept selection would point at another
  fact once the rows change.)
- A facts file with zero facts shows empty tables and no errors.
- Fact text, cited text and model output are shown as plain text, never
  rendered as Markdown or HTML: they come from a PDF and from a model.
- A page image is rendered only for the page on screen.

## 10. Tests

- `tests/test_ui_data.py` (plain pytest, no Streamlit): filters (each alone and
  combined), document order, summary counts, CSV columns and encoding, run
  discovery skipping non-fact JSON, `code_differences`, and `render_page`
  returning a PNG for a PDF built in the test with PyMuPDF, including a
  citation with `bbox: null`.
- `tests/test_ui_app.py` (skipped when Streamlit is missing, via
  `pytest.importorskip`): with `streamlit.testing.v1.AppTest`, the app starts
  on a temporary runs folder holding one small run with no exception; choosing
  a category filter changes the count line; the New run tab's start button is
  disabled until the checkbox is ticked. No test calls the model.
- The existing 73 tests still pass.

## 11. Limits on the build

- Do not change `pipeline.py`, `prompts.py`, `planner.py`, `merge.py`,
  `store.py`, `validate.py` or the output format. The working tree has
  uncommitted changes in those files; build on them as they are.
- Files the build may edit: `cli.py` (add the `ui` subcommand only),
  `pyproject.toml`, `uv.lock`, `.gitignore`, `README.md`, and the new files of
  section 8.
- Do not write under `poc/`. Do not run an extraction or any other command that
  calls the model. Do not commit.

## 12. Done when

1. `uv sync --extra ui` then `uv run fact-extractor ui --runs poc/ablation`
   opens the app and lists the two Ulster runs.
2. Opening `ulster`, picking the Ulster PDF, and selecting a fact shows its page
   with the cited sentence highlighted in the right place.
3. Filters, search and CSV download work on that run; the CSV opens in a
   spreadsheet with the columns of section 7.
4. Compare runs on `ulster` and `ulster_rerun` shows ID agreement 0.884 and
   code agreement 0.55, the figures `fact-extractor stability` prints.
5. All tests pass with and without the `ui` extra installed.
6. README has a short "UI" section: install, launch, what each tab is for.
