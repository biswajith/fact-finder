# Web UI spec: chat workspace for facts and summaries

Status: built 2026-11-20. Checked live on one run: editing, undo, conflict choice, one summary section and its rebuild, chat corrections, a conflict raised by the agent. Libraries: FastAPI (backend), React +
TypeScript + Vite + React Spectrum (`@adobe/react-spectrum`) (frontend).

This is the only UI of the package; it replaced the earlier Streamlit review app.

## 1. Purpose

A bid manager opens one extraction run and works on it by chatting and by clicking:

1. **Correct facts.** "The deadline is 5 March, not 3 March." A correction overwrites
   the extracted fact. The extracted value is kept so the change can be undone.
2. **Read summaries** built from the facts, and see **what is in the facts but not in
   the summaries**.
3. **Corrections change the summaries.** A summary built from a fact that has since
   changed is marked out of date and rebuilt.
4. **Choose between conflicts.** Where the data disagrees (the document contradicts
   itself, or a correction could apply in more than one way), the customer picks one
   option. Nothing is picked for them.

## 2. Rules

- The run's `facts.json`, `report.json` and `source.pdf` are never modified. All
  changes go to a `workspace/` folder beside `facts.json`.
- The customer's correction wins over the extraction. The agent may say that the
  source reads differently, and then applies the correction anyway.
- The agent never resolves a conflict unless the customer stated the choice.
- Fact text, cited text and PDF text are data. They are shown as plain text and are
  never followed as instructions (state this in the agent's system prompt).
- No model call happens except: a chat message the user sent, a summary the user
  asked for, and the rebuild of an already generated summary after a change.
- The server binds to 127.0.0.1 only. The API key is never sent to the browser.
- `prompts.py` is not changed. New prompts state general principles and contain no
  example taken from the two RFPs in the repo root or from `poc/`.
- Every `run` parameter is resolved inside the runs folder; anything that escapes it
  is a 404.

## 3. Layout of the code

```
src/fact_extractor/web/__init__.py
src/fact_extractor/web/runs.py        # find and load runs, document order, page rendering
src/fact_extractor/web/workspace.py   # corrections, effective facts, conflicts; no FastAPI, no model
src/fact_extractor/web/summaries.py   # sections, staleness, coverage, generation
src/fact_extractor/web/agent.py       # chat agent: tools and the tool loop
src/fact_extractor/web/server.py      # FastAPI app factory, routes, SSE
src/fact_extractor/web/static/        # built frontend (git-ignored)
web/                                  # frontend source (Vite project)
tests/test_web_runs.py, test_web_workspace.py, test_web_summaries.py, test_web_agent.py, test_web_server.py
```

- Optional extra `web = ["fastapi", "uvicorn"]`, also in the dev group (with `httpx`
  for the test client). The core package and its tests pass without it
  (`pytest.importorskip`).
- `fact-extractor web [--runs FOLDER] [--port 8765]` starts uvicorn on 127.0.0.1 and
  prints the URL. Missing extra: print the install command, exit 1.
- `src/fact_extractor/web/runs.py` holds `find_runs`, `load_run`, `normalize`,
  `document_order` and `render_page` (no FastAPI, no model).

## 4. Workspace files

In `<run folder>/workspace/`:

| File | Content |
| --- | --- |
| `corrections.jsonl` | Append-only log, one JSON object per line |
| `summaries.json` | Generated sections and pinned fact IDs |
| `chat.jsonl` | Chat messages, one per line |

### 4.0 Base fact record

One element of `facts.json`, as the extractor writes it:

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
  `post-award`.
- `citations[].page` is the 1-based page of the PDF file; `page_label` is the
  number printed on the page and may differ. `bbox` is `[x0, y0, x1, y1]` in
  PDF points with the origin at the top left, as PyMuPDF reports it; it can be
  `null`.
- `conflicts` holds the `fact_id`s of Q facts that cite the same source.
- `problems` holds the reasons a fact is `needs_review`.

### 4.1 Correction log entry

```json
{"id": "c_1a2b3c4d", "at": "2026-11-20T10:00:00Z", "source": "chat",
 "op": "edit", "fact_id": "f_65ed2f51cf",
 "fields": {"text": "..."}, "reason": "customer said ...",
 "conflict_id": null, "target": null}
```

`source` is `chat` or `ui`. Operations:

| `op` | Meaning | Uses |
| --- | --- | --- |
| `edit` | Overwrite fields of a fact. Allowed fields: `text`, `category`, `flags`, `note` | `fact_id`, `fields` |
| `delete` | Reject a fact | `fact_id` |
| `add` | New fact written by the customer | `fact_id` (new, `u_` + 10 hex), `fields` with `category`, `text`, optional `flags`, `note`, `citation_ids` |
| `raise` | Record a conflict the agent found | `conflict_id`, `fields` = the conflict (4.3) without status |
| `resolve` | The customer's choice | `conflict_id`, `fields` = `{"option": 0}` or `{"option": null, "text": "custom"}` |
| `undo` | Cancel one earlier entry | `target` = that entry's `id` |

The effective state is the base facts with the log replayed in order, skipping every
entry that an `undo` targets. Undoing a `resolve` reopens the conflict. Later edits
of the same field win.

### 4.2 Effective fact

The base record (4.0) plus:

```json
{"origin": "extracted", "edited": true, "deleted": false,
 "original": {"text": "the extracted text"},
 "resolution": null,
 "corrections": ["c_1a2b3c4d"]}
```

- `origin`: `extracted` or `user` (added by the customer).
- `original`: the base value of each field that now differs, else `null`.
- `corrections`: IDs of the live log entries that touch this fact.
- `resolution` (Q facts only): `{"conflict_id", "label", "text", "at"}` once resolved.
- A user fact's `citations` are built from `citation_ids` when the tagged document is
  available and the IDs exist; unknown IDs go to `unresolved_ids`.
- Deleted facts are left out of every list unless `include_deleted=1`.

### 4.3 Conflict

```json
{"id": "q:f_e844035e60", "kind": "source", "title": "...", "description": "...",
 "fact_ids": ["f_e844035e60", "f_3f3dd7631c"],
 "options": [
   {"label": "Page 11: Term", "text": "the cited sentence",
    "citation": {"id": "p11.3", "page": 11, "page_label": "11", "section": "..."},
    "changes": []}
 ],
 "status": "open",
 "resolution": null}
```

Two kinds:

- **`source`**: one per Q fact (a contradiction inside the document). `id` is
  `q:<fact_id>`. `title` is the Q fact's text. One option per citation of the Q fact:
  `label` "Page <page_label>: <section>", `text` the cited text. `fact_ids` is the Q
  fact followed by every fact whose `conflicts` lists it.
- **`raised`**: recorded by the agent with the `raise` operation. `id` is `k_` + 8 hex.
  Each option carries `changes`: a list of `{"op": "edit" | "delete", "fact_id",
  "fields"}` that become corrections if that option is chosen.

Resolving (`resolve`):

- `resolution` becomes `{"option": 0 | null, "label", "text", "at"}`; `status` becomes
  `resolved`. A custom answer has `option: null` and the customer's text.
- `raised`: the chosen option's `changes` are applied as corrections, logged with
  the same `conflict_id` (undoing the `resolve` cancels them too).
- `source`: the Q fact gets `resolution`. Every linked fact with status `conflict`
  becomes `valid`. A linked fact that cites the unit of a losing option and not the
  unit of the chosen option gets the flag `replaced`. A custom answer adds no
  `replaced` flag.

## 5. Summaries

Sections, each built from the effective facts of its categories (deleted facts and
facts flagged `replaced` are left out):

| Key | Title | Categories |
| --- | --- | --- |
| `overview` | Buyer and scope | B |
| `dates` | Key dates | D |
| `gates` | Go/no-go gates and disqualifiers | G, X |
| `submission` | How to submit | S |
| `evaluation` | How bids are scored | E |
| `contract` | Contract terms and risks | C |
| `requirements` | Requirements | R |

Resolved Q facts are passed to the section of each fact they link to, as "the customer
decided: <resolution text>".

Section as returned by the API:

```json
{"key": "dates", "title": "Key dates",
 "points": [{"text": "Bids are due ...", "fact_ids": ["f_..."]}],
 "generated_at": "2026-11-20T10:00:00Z", "stale": false, "updating": false,
 "fact_count": 16, "uncovered": ["f_..."], "pinned": ["f_..."], "error": null}
```

- **Generation**: one model call per section. The model gets the section's facts as
  lines `fact_id|category|flags|text` and answers one point per line as
  `point text|fact_id,fact_id`. Code drops IDs that are not in the section and drops
  points left with no ID. The prompt asks for what a bid manager must know to decide
  and to plan the bid, at most 12 points, each point supported only by the facts it
  cites, pinned facts always cited, and changed or customer-written facts treated as
  the truth.
- **Stale**: a section stores a hash of its input (fact ID, category, flags, text and
  resolution of every fact in it, the customer's decisions on resolved conflicts that
  touch its facts, plus the pinned IDs). It is stale when the current hash differs.
  A decision counts whether or not it changed a fact: the chosen option's text (or the
  custom answer) is given to the model as "conflict title -> choice", both for
  conflicts the extraction found and for conflicts the chat agent raised. A section never generated has `generated_at: null` and `stale: false`.
- **Not verified**: a row whose wording has a figure (amount, date, number) that is not in the
  facts it cites, or that cites no facts, fails the figure check. Its wording is never shown:
  the screen shows the cited facts instead (or nothing), flagged "Not verified" with the
  figures that failed (`unverified` on the row).
- **Uncovered** ("in the facts, not in the summary"): the section's facts that no
  point cites, in document order. Empty when the section was never generated.
- **Pin**: `pinned` fact IDs must appear in the summary. Pinning makes the section
  stale.
- **Rebuild after a change**: after any change to facts, conflicts or pins, the server
  starts a background rebuild of every stale section that has been generated before.
  One rebuild per run at a time; a change during a rebuild triggers another pass.
  `updating` is true while a section is queued or running. A failed call sets `error`
  and leaves the old points.

## 6. API

All under `/api`. `run` is the run's folder path relative to the runs folder (the
folder that holds `facts.json`), as a query parameter. JSON in and out. Errors:
`{"detail": "message"}` with 400, 404 or 409.

| Method and path | Body | Returns |
| --- | --- | --- |
| `GET /status` | | `{"model", "has_key", "runs_folder"}` |
| `GET /runs` | | `[{"run", "doc_id", "run_id", "facts", "modified", "has_pdf", "corrections"}]` newest first |
| `GET /facts?run=&include_deleted=` | | `{"doc_id", "run_id", "pages", "facts": [effective fact]}` in document order |
| `POST /facts?run=` | `{"category", "text", "flags"?, "note"?, "citation_ids"?}` | effective fact |
| `PATCH /facts/{fact_id}?run=` | any of `text`, `category`, `flags`, `note`; optional `reason` | effective fact |
| `DELETE /facts/{fact_id}?run=` | optional `{"reason"}` | `{"ok": true}` |
| `POST /facts/{fact_id}/restore?run=` | | effective fact (undoes every live entry on it) |
| `GET /corrections?run=` | | `[log entry + "undone": bool + "fact_text"]` newest first |
| `POST /corrections/{id}/undo?run=` | | `{"ok": true}` |
| `GET /conflicts?run=` | | `[conflict]` open first |
| `POST /conflicts/{id}/resolve?run=` | `{"option": 0}` or `{"text": "custom"}` | conflict |
| `POST /conflicts/{id}/reopen?run=` | | conflict |
| `GET /summaries?run=` | | `{"sections": [section], "updating": bool}` |
| `POST /summaries/generate?run=` | `{"sections": ["dates"]}` or `{}` for all | `{"sections": [...], "updating": true}` (starts in the background) |
| `POST /summaries/pin?run=` | `{"fact_ids": [...], "pinned": true}` | summaries |
| `GET /page?run=&page=&fact_id=` | | PNG of the page, the fact's citations on it highlighted; 404 without a PDF |
| `GET /chat?run=` | | `[chat message]` oldest first |
| `DELETE /chat?run=` | | `{"ok": true}` (clears the history, not the corrections) |
| `POST /chat?run=` | `{"message": "..."}` | `text/event-stream` (6.1) |
| `GET /chat/sessions?run=` | | `[session]` newest first: `session_id`, `started`, `turns`, `last`, `current`, `totals` (7.2) |
| `GET /chat/sessions/{session_id}?run=` | | `{"session": session, "events": [event]}`; 404 for an unknown id |
| `DELETE /chat/sessions/{session_id}?run=` | | `{"ok": true, "deleted": [id], "chat_cleared": bool}`: deletes the session's log; deleting the current session also clears the chat |
| `DELETE /chat/sessions?run=` | | the same shape: deletes every session log of the run and clears the chat |

Every write is logged with `source: "ui"` except those the agent makes.

### 6.1 Chat stream

Each event is one line `data: <json>` followed by a blank line.

```json
{"type": "text", "delta": "The deadline "}
{"type": "tool", "name": "edit_fact", "label": "Changed fact f_65ed2f51cf", "ok": true}
{"type": "changed", "what": ["facts", "conflicts", "summaries"]}
{"type": "conflict", "conflict_id": "k_1a2b3c4d"}
{"type": "plan", "mode": "heavy", "source": "router", "confidence": 0.82, "status": "awaiting_approval",
 "steps": [{"step": "Find the deadlines", "done": false}]}
{"type": "error", "message": "OPENAI_API_KEY is not set"}
{"type": "done", "message": {chat message}}
```

`plan` is sent only when planning is on (section 7.1): once when the mode is known, and
again after each `update_plan` call. The frontend may ignore it; the plan and the
approval question are also in the `text` deltas.

Chat message:

```json
{"id": "m_1a2b3c4d", "role": "assistant", "at": "...", "text": "...",
 "tools": [{"name": "edit_fact", "label": "...", "ok": true}],
 "conflict_ids": ["k_1a2b3c4d"],
 "planning": {"mode": "light", "source": "router", "status": "awaiting_approval", "plan_text": "Plan: 1) ..."}}
```

Every message also carries `session_id` and `turn_id` (7.2); a reply has the turn id of
the customer message it answers.

`planning` is on assistant messages only when planning is on; it is the `plan` event's
content at the end of the turn, and how the next turn finds a plan waiting for approval.

The assistant refers to a fact as `[f_65ed2f51cf]` in its text; the frontend shows
these as links that open the fact.

## 7. The agent

`agent.py` runs a tool loop on the OpenAI Chat Completions API (reasoning effort `none`: the model rejects tools with reasoning on that API) with streaming and
tool calls (model from `FACT_EXTRACTOR_MODEL`, default `gpt-6-luna`; check the
installed `openai` package for the exact streaming tool-call shapes). The model is
behind a small protocol so tests use a scripted model and never call the API. At
most 8 tool rounds per message; the last 20 chat messages are sent as history.

The system prompt holds the rules of section 2, the category names, the counts per
category and the number of open conflicts. Facts are not in the prompt; the agent
reads them with tools.

| Tool | Does |
| --- | --- |
| `search(query?, queries?, section?, label?, category?, flag?, status?, edited?, limit=10)` | Word search over the labelled text of the whole document (`labels.json`) and the facts; each row's section heading is searched with it, since a section's sentences often do not repeat the topic of the heading. A hit is a fact row (`fact_id`, category, fact line, page, section; flags, status and `edited` only when set) or, for source text with no fact, a unit row (`unit_id`, label, `unit_text` cut at 400 characters); `votes` only when they disagreed. Ranked by the sum of the squared rarity (inverse frequency) of the query terms a row matches, so rare words outweigh common ones; rows under 25% of the best score are left out. `queries` runs up to 10 searches in one call under the same filters, at most 6 hits each. A row already returned in full earlier in the turn comes back as its ID with `sent_before`. `more` counts matches not shown; `section` (part of a heading) keeps only that section's rows |
| `get_fact(fact_id? , fact_ids?)` | Full effective fact with cited source text and section and its original values; `fact_ids` reads up to 20 in one call; empty fields are left out |
| `edit_fact(fact_id, text?, category?, flags?, note?, reason, values_removed?)` | Correction of a fact that is wrong. A new text that drops more figures (amounts, dates, numbers) than it adds is refused unless `values_removed` is true |
| `delete_fact(fact_id, reason)` | Correction |
| `add_fact(category, text, flags?, citation_ids?, note?)` | New customer fact: something the extraction missed, or new information from the buyer (a clarification or update), cited to the related source unit. New information never rewrites an extracted fact. The new fact is checked for contradictions (7.3) |
| `restore_fact(fact_id)` | Back to the extracted value |
| `list_conflicts(status?)` | Conflicts with their options |
| `raise_conflict(title, description, fact_ids, options)` | Record a conflict for the customer to choose; use when a correction could apply to several facts in ways that differ, or facts disagree |
| `resolve_conflict(conflict_id, option?, text?)` | Only when the customer stated the choice |
| `get_summary(section?)` | Points with their fact IDs, stale flag |
| `facts_not_in_summary(section?)` | Uncovered facts |
| `pin_to_summary(fact_ids, pinned=true)` | Pin or unpin |
| `generate_summary(sections?)` | Start generation; answers at once, the UI shows progress |

Tool results are JSON. A tool error is returned to the model as `{"error": "..."}`
and reported in the stream with `ok: false`.

### 7.1 Planning

`planning.py` decides, per customer message, whether the agent plans before it acts.
There are three modes, so each can be measured against the others:

| Mode | What happens |
| --- | --- |
| `direct` | The plain tool loop above: the model decides one round at a time. |
| `light` | The model writes its steps in one line (`Plan: 1) ... 2) ...`) and follows them. |
| `heavy` | A planning call with no tools writes the steps as JSON. The loop carries them out with an extra tool, `update_plan(done?, revise?)`, that ticks steps off or replaces the ones not yet done, and gets 16 tool rounds, not 8. |

**Which mode.** `FACT_EXTRACTOR_CHAT_PLANNING`: `auto` (default) asks the OpenAI Decisions
API one `Choice` question (`direct` / `light` / `heavy`, judged by the work the message
needs) over the last 6 chat messages, the workspace counts and the new message. A pick
below confidence 0.6 runs `light`; a failed call runs `direct`. `direct` (or `off`),
`light` and `heavy` force one mode for every message (the baselines).
`FACT_EXTRACTOR_DECISIONS_MODEL` sets the Decisions model (default `gpt-6-luna`).

**Approval.** `FACT_EXTRACTOR_CHAT_PLAN_APPROVAL`: `on` (default: light and heavy),
`heavy`, or `off`. In a mode that needs approval the agent writes the plan with no tools,
shows it, asks "Shall I go ahead? You can also tell me what to change.", and ends the turn
having changed nothing. The customer's next message is judged by a second Decisions
`Choice` question:

| Verdict | What happens |
| --- | --- |
| `approve` | The stored plan runs (heavy: the stored steps with `update_plan`). |
| `revise` | The plan is written again with the customer's changes and shown again. |
| `cancel` | A fixed reply; no model call, nothing changed. |
| `new_request` | The plan is dropped and the message is routed like any other. |

Anything but a confident `approve` counts as `revise`, so no plan runs without a clear yes.
Without an approval mode, `light` plans inline in the loop and `heavy` shows its steps and
carries them out in the same turn.

### 7.2 Chat sessions and their log

A chat session runs from the first message to the next "clear chat" (`DELETE /chat`), and
has an id `s_` + 12 hex. Each customer message is a turn, with an id `t_` + 10 hex. Every
turn is written to `<run>/workspace/chat/<session_id>/events.jsonl` (append-only; the
folder also holds `session.json`, and `workspace/chat/current.json` names the current
session). Clearing the chat ends the session but keeps its folder. Each event has `at`,
`session_id`, `turn_id`, `seq` and `event`:

| Event | Fields |
| --- | --- |
| `user_message` | `text` |
| `feedback` | the plan shown, `verdict`, `source`, `confidence`, `note`, and `call` (the Decisions call: `model`, `input_tokens`, `seconds`, `error`) |
| `route` | `mode`, `source`, `confidence`, `probabilities`, `note`, `call` as above |
| `plan` | the plan record (`steps` or `plan_text`, `status`); again after each `update_plan` |
| `llm_call` | `purpose` (`plan_heavy`, `plan_light`, `loop`, `final`), `round`, `messages`, `tools_offered`, `tools_allowed`, `tool_calls` (name and clipped arguments), `text_chars`, `input_tokens`, `cached_tokens`, `output_tokens`, `seconds`, `error` |
| `tool` | `name`, `round`, `args`, `ok`, `summary`, `seconds` |
| `consistency_check` | `fact_id`, `checked_against`, `findings` (fact ID and probability each), `conflicts_raised`, `skipped`, `call` (the Decisions call) |
| `assistant_message` | `text`, `tools` (count), `conflict_ids`, `planning` |
| `turn_end` | `totals`: `llm_calls`, `tool_calls`, `decisions_calls`, `input_tokens`, `cached_tokens`, `output_tokens`, `decisions_input_tokens`, the seconds spent in each, and the turn's `seconds`; `error` |

Tokens come from the API's usage report (`stream_options.include_usage`). A failed write to
the log is counted on `turn_end` (`write_errors`) and never stops the chat.

Cost: `llm_call`, each Decisions `call` and the totals carry `cost_usd` (the totals also
`llm_cost_usd` and `decisions_cost_usd`), estimated from the price table in `pricing.py` when
the event is logged. Uncached input is priced at the input rate (the API may bill part of it
as a cache write, 1.25x), and Decisions input as uncached. Events logged before costs existed
are priced when read, at today's prices, and their `turn_end` is marked `cost_added_later`.
Summary rebuilds are separate model calls and are not in the chat log.

### 7.3 Checking added and edited facts

Extracted facts are compared with each other during extraction; a fact added later, by the
customer (`POST /facts`) or the chat (`add_fact`), or whose text is edited (`PATCH /facts`,
`edit_fact`), is checked by `consistency.py`, since one value is often written in several facts:

1. The 8 existing facts closest to it by the chat's search ranking (itself, deleted and
   replaced facts left out).
2. One Decisions API request with a Predicate per fact: do the two give different values,
   dates, amounts, counts or rules for the same thing, so that one must be wrong or out of
   date? Different minimums or limits for the same thing count, even when meeting one meets
   the other; added detail, a condition or a later possibility does not.
3. Each fact at probability 0.7 or more gets a raised conflict with three options, each
   carrying its changes: the added fact applies (the existing one is kept, flagged
   `replaced`, with a note), the existing fact stands (the added one is deleted), or both
   are true (no change). Nothing is resolved automatically.

For an edit, the options are: the other fact is out of date (it is flagged `replaced`), or
both are true. In the chat, an edit raises no conflict: the facts found go back to the agent
in `may_be_out_of_date`, and its rules say a changed value applies to every fact stating it,
so it updates them in the same turn (or raises a conflict when it is unclear).

A missing key or failed call skips the check; the fact stays added. `POST /facts` returns
the fact with `check` (`checked_against`, `conflicts_raised`, `check_skipped`); the chat's
`add_fact` result carries the same and tells the agent not to resolve the conflict. Like
planning, the check runs only with the real chat model unless a checker is passed to
`create_app`.

## 8. Frontend

`web/`: Vite, React, TypeScript, `@adobe/react-spectrum` (Provider with the default
theme, light and dark following the system). No other UI library. `npm run dev`
proxies `/api` to `http://127.0.0.1:8765`. `npm run build` writes to
`../src/fact_extractor/web/static`. The server serves that folder at `/`; when it is
missing, `/` answers with a plain page giving the build command.

One screen:

- **Header**: product name, run picker (doc ID, run ID, fact count), counts of open
  conflicts and changes, a notice when no API key is set.
- **Main area**, tabs:
  - **Summary**: one block per section. Points as a list; each point shows its cited
    facts as small links. "Out of date" and "Updating" badges. A "Generate" button
    for sections never generated and "Generate all". Under each section a
    collapsible "In the facts, not in this summary (N)" list, each row with "Add to
    summary" (pin). Pinned facts are marked.
  - **Facts**: category filter with counts, search, switches for "Changed only" and
    "Show deleted". One row per fact: category, text, flags, page, a "Changed" badge.
    Opening a fact shows: text, original text when changed, flags, note, citations
    with cited text, the PDF page image with highlights, and actions Edit (form:
    text, category, flags, note), Delete, Restore, Ask in chat (puts
    `About [fact_id]: ` in the chat box). An "Add fact" button.
  - **Conflicts**: one card per conflict, open first. Title, description, the options
    as a radio group with their text and page, a text field for a custom answer, and
    "Use this choice". Resolved conflicts show the choice and "Reopen".
  - **Changes**: the correction log, newest first: what changed (before and after),
    when, from chat or UI, and "Undo".
  - **Chat log** (`#/chatlog`, under Run): the chat sessions of the run (7.2), newest
    first; for the selected one, its totals (turns, LLM, tool and Decisions calls,
    input tokens and the cached share, output tokens, estimated cost) and each turn
    with its cost: the customer's
    message, the feedback on a plan, the planning mode and why, the plan and its
    status, a table of the LLM calls (purpose, round, tokens, time) with the tool runs
    each asked for under it, and the reply (folded). "Delete session" and "Delete all"
    remove session logs after a confirmation; when the current session goes, the
    Assistant's history is cleared too. Facts and changes are not touched.
- **Chat panel** on the right, always visible on wide screens, a toggle on narrow
  ones. Messages stream in. Tool steps show as small status lines. A conflict the
  agent raised shows inline as the same choice card as on the Conflicts page. Fact
  links open the fact. Starter prompts when the history is empty. "Clear chat".

After a `changed` event or any write, the frontend reloads facts, conflicts,
corrections and summaries. While summaries are `updating`, it polls
`GET /summaries` every 2 seconds.

All text from facts, the PDF and the model is rendered as text, never as HTML.
Every control has an accessible label. The layout works from 1024 px wide; below
that the chat becomes a toggled panel.

## 9. Tests

Backend, all offline: replay and undo, each operation, both conflict kinds and their
resolution effects, staleness, coverage, pins, output parsing of a summary, the
agent loop with a scripted model (edit, raise conflict, tool error, round limit),
every route with FastAPI's test client, path escape in `run`, SSE format.

Frontend: `npm run build` and `npx tsc --noEmit` pass; unit tests (vitest) for the
API client's SSE parsing and for turning `[f_...]` tokens into links.

## 10. Done when

1. `uv sync --extra web`, `npm --prefix web install`, `npm --prefix web run build`,
   then `fact-extractor web --runs runs` opens the app and lists the runs.
2. Editing a fact on the Facts page shows it as changed, lists it under Changes, and
   Undo brings the extracted text back.
3. Choosing an option on a source conflict marks it resolved and clears the conflict
   status of its linked facts.
4. With an API key: "Generate" builds a section; editing one of its facts marks it
   out of date and it rebuilds; the uncovered list and "Add to summary" work.
5. With an API key: a correction typed in chat changes the fact and is listed under
   Changes with source chat.
6. All Python tests pass with and without the `web` extra.

## 11. Review routes and screens

Added 2026-11-20. The helpers behind these routes live in `web/runs.py`.
Everything below works on the **effective** facts (corrections applied, deleted
facts left out), so a correction shows up here too.

### 11.1 Routes

| Method and path | Body | Returns |
| --- | --- | --- |
| `GET /overview?run=&view=` | | `{"overview": runs.overview(facts in view, the report's stored summaries), "counts": {"needs_review", "conflicts", "risk", "mandatory", "unclear"}, "by_category": {code: n}, "has_post_award": bool, "views": ["All", "Bid", "After award"]}` |
| `GET /facts/list?run=&q=&categories=&statuses=&flags=&page_from=&page_to=&view=&split_only=&edited=&include_deleted=` | | `{"total": n, "by_category": {code: n under the other filters}, "items": [{"kind", "fact_ids": [...]}], "facts": [effective fact]}` using `runs.filter_facts`, `runs.document_order` and `runs.items`. List parameters are comma-separated. `GET /facts` stays as it is |
| `GET /facts.csv?run=` + the same filters | | CSV from `runs.to_csv`, `Content-Disposition: attachment` with `runs.csv_name` |
| `GET /report?run=` | | the run's `report.json`, or 404 when it has none |
| `GET /runs/table` | | `runs.runs_table(all runs)` |
| `GET /compare?a=&b=` | | `{"agreement": stability.compare_runs(a, b), "code_differences": runs.code_differences(a, b)}`; 400 when the two runs have different `doc_id` |
| `GET /pdfs` | | `[{"path", "name"}]` from `runs.pdfs_in(".")` |
| `POST /uploads?name=` | raw `application/pdf` body, at most 100 MB | `{"upload_id", "name", "pages"}`; kept in a temporary folder for the life of the server |
| `POST /extract/plan` | `{"path" or "upload_id", "doc_id", "votes": 1 \| 3 \| 5}` | `{"calls": runs.plan_rows(...), "total_calls", "units", "stored": null \| {"run", "facts", "created"}}`. No model call |
| `POST /extract` | `{"path" or "upload_id", "deal_id", "doc_id", "model"?, "votes", "confirm": true}` | `{"job_id"}`. 400 unless `confirm` is true, the key is set, and deal ID and doc ID are given. Runs `runs.run_extraction(..., refresh=True)` in the background; one extraction at a time (409 otherwise) |
| `GET /extract/{job_id}` | | `{"status": "running" \| "done" \| "failed", "seconds", "result": runs.result_line(report) \| null, "run": new run path \| null, "error": null \| str}` |

`GET /facts` and `/facts/list` add three computed booleans to each fact:
`post_award`, `affects_bid` and `split` (`runs.is_post_award`, `affects_bid`,
`is_split`).

Starting an extraction is the one new place a model is called; it needs explicit
confirmation.

### 11.2 Screens

- **Overview page**: an "At a glance" block above the written sections: the five counts, buyer card, calendar of dates, submission
  instructions, go/no-go gates and what gets a proposal rejected, scoring criteria,
  clarifications (contradictions and unclear points), each with the facts it was
  built from folded underneath, and the All / Bid / After award switch with its
  help text and the note shown when a run marks nothing as post-award.
- **Facts page**: the view switch, status and flags filters, page range, "Split
  votes only", facts per page (60, 120, 240; 60 by default), search over fact text and cited text
  (server-side, `/facts/list`), category chips with the count under the other
  filters, grouping (a point stated in several places shown once; sibling facts as
  one expandable card), `problems` and `unresolved_ids` in the fact detail, and
  "Download CSV" for the filtered rows.
- **Report page**: totals (total time, output tokens, cache hit,
  calls by status, failed and incomplete calls), the table of calls, the selected
  call's log and raw output as preformatted text, and the table of all runs. A
  message when the run has no report.
- **Compare page**: two run pickers (run B limited to the same `doc_id`), the three
  agreement figures, the per-category table, code differences, and the table of source
  IDs filed under different codes.
- **Documents page** (replaces the New run page; `#/new` still opens it, and so does `#/documents`):
  it sits first in the Review group. Pick a bid or start one, add its documents
  (PDF, spreadsheet, call transcript, deal notes), say what each one is (type, issue
  number and date; the proposal is marked "suggested"), confirm the speakers of a
  transcript, list the team, set the order of precedence if the buyer gave one, see the
  planned calls, tick "I understand this spends API tokens" and extract. The old
  single-PDF routes in 11.1 still exist; the page no longer uses them. A bid
  with facts opens like a run (`_bids/<bid_id>`). Section 11.3 lists the routes.
- **Header**: pages and PDF name beside the run; when the run has no PDF, a control
  to pick one from the working directory or upload one.

### 11.3 Bids: many documents, one fact list

A bid is a folder `runs/_bids/<bid_id>/`. It opens like a run, as `_bids/<bid_id>`.
Everything below is shown only in a bid: `GET /facts` adds `documents` only for a bid,
and the page treats a non-empty `documents` as "this is a bid". A single-document run
looks as before.

Routes (all under `/api`; errors are `{"detail"}` with 400, 404, 409 or 413):

| Method and path | Body | Returns |
| --- | --- | --- |
| `GET /bids`, `POST /bids` | `{name, deal_id?}` | list of `{bid_id, name, run, documents, facts, modified}`; the new bid |
| `GET /bids/{bid}`, `PATCH /bids/{bid}` | `{name?, team?, precedence?}` | the manifest plus `order` (doc IDs in issue order), `run` and `playbooks` |
| `POST /bids/{bid}/documents?name=` | the raw file | the new document entry, with a proposed type, issue number and date |
| `PATCH /bids/{bid}/documents/{no}`, `DELETE ...` | `{doc_id?, playbook?, issue_number?, issue_date?, previous?, confirmed?, speakers?, speakers_confirmed?}` | the entry; `{ok}` |
| `POST /bids/{bid}/plan` | `{votes?}` | planned calls per document; no model call |
| `POST /bids/{bid}/process` | `{confirm: true, votes?, model?}` | `{job_id}`; `GET /extract/{job_id}` then lists `steps` per document |
| `POST /relations/{rid}/reject?run=` | | `{ok, relation_id, rejected, facts}`. The relation leaves the facts. Undo it on the Changes page |
| `POST /groups/{gid}/ungroup?run=` | | `{ok, group_id, ungrouped, facts}`. Undo it on the Changes page |
| `GET /facts?run=` | | for a bid, also `documents: [{no, doc_id, file_name, playbook, level, visibility, issue_date, issue_number, has_pdf}]` |
| `GET /facts/list`, `GET /facts.csv` | `docs=1,2`, `levels=1,4` | as before; the CSV also takes `audience=external` (internal citations left out, and a fact with none left) |
| `GET /page?run=&page=&fact_id=&doc=` | | the page image of document `doc` (a doc ID) |

New fields on a fact in a bid: `doc_no`, `level` (1 buyer document, 2 buyer on a
call, 3 our side on a call, 4 deal notes), `playbook`, `relations` (each
`{id, kind, from, to, rejected}`, on both facts), `replaced_by` (a fact ID or ""),
`stale` ("" or a warning). New flags: `tentative`, `precedence`, `both-sides`. New
category codes: `PRIORITY` (Buyer priority), `DECIDER` (Decision maker), `BUDGET`,
`QUESTION` (Open question), `COMPETITOR`, `ACTION` (Action for our team). New fields
on a citation: `doc_id`, `doc_no`, `speaker`, `side`, `level`, `visibility`. For a
transcript the page label is the time.

A conflict of kind `document` has a `reason` (`user-edited fact replaced`,
`old value elsewhere`, `depends on changed value`, `levels disagree`,
`unfound target` or `issued together`) and `closed_by` (the doc ID of a later
document that settled it, or ""). An option may have `question: true` and a change
may have `add_flag`.

Changes entries of the ops `reject_relation` and `ungroup` carry a `description` line
and an Undo button like any other entry.

Screens in a bid:

- **Facts page**: a citation reads `d2 · p.4` (`d1 · 00:04:12 · Dana Whitcomb` for a
  transcript), its tooltip is the file name, and an internal source is marked
  "Internal". Each fact shows a level chip ("L1 · Buyer document" to "L4 · Deal notes").
  A replaced fact is dimmed and has a "Replaced" pill; a `stale` fact has a line "Check: ...".
  A point stated in several documents is one row with every citation and an "Ungroup"
  button. Filters: Documents, Levels, and "Hide replaced", which is on by default and
  is applied in the browser to the list the server returns. Two downloads:
  "CSV for the team" and "CSV to share (no internal sources)".
- **Fact detail**: "Replaced by" with a link to the fact that governs it ("Removed by
  a later document" when a REMOVES relation points at it); each relation as one line
  ("Replaces ...", "Confirmed by ...") with a "Reject" button; clicking a citation
  chip opens the page image only when that document has a PDF, and the cited text
  with its speaker and time is always shown.
- **Conflicts page**: a `document` conflict shows its reason in words, each fact with
  its document and level, a "tentative" mark where the flag is set, and for each
  option a line saying what it changes ("Marks ... replaced", "Changes the text to
  ...", "No change"). An option with `question: true` ("Ask the buyer") is a third,
  quieter choice. "Settled by <document>" shows when a later document closed it.
- **Overview page**: the counts row also shows "Replaced" and "Internal only".
