"""Fact review app (UI_SPEC.md). Streamlit layout only; the work is in `data.py`.

Launch with `fact-extractor ui`, or `streamlit run src/fact_extractor/ui/app.py`,
from the project folder. Runs are read from `runs/` and nowhere else.

Text that comes from a PDF or a model is never rendered as Markdown or as markup
(UI_SPEC.md section 9): it goes through st.text, st.code, tables, or through `esc`
(html.escape) into the app's own HTML in `style.py`.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections import Counter
from pathlib import Path

import pandas as pd
import streamlit as st

from fact_extractor.cli import load_env
from fact_extractor.models import CATEGORIES, FLAGS
from fact_extractor.stability import compare_runs
from fact_extractor.ui import data as D
from fact_extractor.ui import style as S

NO_PDF = "(none)"
UPLOAD_PREFIX = "uploaded: "


def _md_escape(text: str) -> str:
    """For the few places Streamlit only offers Markdown (warning and info boxes)."""
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|<>~$:])", r"\\\1", text)


# Every run lives in this one folder, as runs/<doc_id>/<run>/facts.json: results the
# pipeline stores, and the earlier pipeline's runs moved there on 2026-11-18. The app
# reads nowhere else, so there is no folder to choose and none to get wrong.
RUNS = "runs"


# --- cached work ----------------------------------------------------------------------


@st.cache_data(show_spinner="Looking for runs...")
def find_runs(folder: str) -> list[D.RunRef]:
    return D.find_runs(folder)


@st.cache_data(show_spinner=False)
def load_run(path: str, mtime: float) -> D.Run:  # mtime: reload when the file changes
    return D.load_run(path)


@st.cache_data(show_spinner=False, max_entries=64)
def render_page(pdf: str | bytes, page: int, boxes: tuple, zoom: float = 1.5) -> bytes:
    return D.render_page(pdf, page, [list(b) if b else None for b in boxes], zoom)


@st.cache_data(show_spinner="Reading the PDF...", max_entries=8)
def plan_for(pdf_bytes: bytes, doc_id: str, votes: int) -> tuple[list[dict], int]:
    doc = D.tag_pdf(pdf_bytes, doc_id)
    return D.plan_rows(doc, votes), len(doc.anchors)


def _key(*parts) -> str:
    return hashlib.md5(repr(parts).encode()).hexdigest()[:12]


# --- sidebar --------------------------------------------------------------------------


def _apply_pending() -> None:
    """A finished new run asks for itself to be selected; widgets can only be set before they render."""
    run = st.session_state.pop("_pending_run", None)
    if run:
        st.session_state["_want_run"] = run
        st.session_state.pop("new_confirm", None)  # the next run needs a fresh confirmation


def _run_label(ref: D.RunRef) -> str:
    took = D.took(ref.seconds)
    name = ref.label.removesuffix("/facts.json") + ("" if ref.stored else "  ·  earlier pipeline")
    return f"{name}  ·  {ref.facts} facts" + (f"  ·  {took}" if took else "")


def sidebar() -> tuple[list[D.RunRef], D.Run | None, str | bytes | None, str]:
    st.sidebar.html(S.BRAND)
    st.sidebar.header("Run")
    if st.sidebar.button("Refresh", help=f"Look again for runs in the {RUNS}/ folder."):
        find_runs.clear()
    runs = find_runs(RUNS)
    if not runs:
        st.sidebar.info(f"No runs yet in {RUNS}/. Start one in the New run tab.")
        return runs, None, None, ""

    by_path = {str(r.path): r for r in runs}
    want = st.session_state.pop("_want_run", None)
    if want:
        target = Path(want).resolve()
        for p in by_path:
            if Path(p).resolve() == target:
                st.session_state["run_choice"] = p
    if st.session_state.get("run_choice") not in by_path:
        st.session_state["run_choice"] = str(runs[0].path)
    choice = st.sidebar.selectbox(
        f"Run ({len(runs)} in {RUNS}/, newest first)", list(by_path), key="run_choice",
        format_func=lambda p: _run_label(by_path[p]),
    )
    ref = by_path[choice]
    st.session_state["_took"] = D.took(ref.seconds)
    run = load_run(str(ref.path), ref.mtime)

    st.sidebar.header("PDF")
    pdf, pdf_name = _pick_pdf(run)
    return runs, run, pdf, pdf_name


def _pick_pdf(run: D.Run) -> tuple[str | bytes | None, str]:
    if run.pdf:
        st.sidebar.text("source.pdf beside the run")
        return str(run.pdf), run.pdf.name
    remembered: dict = st.session_state.setdefault("pdf_by_doc", {})
    uploads: dict = st.session_state.setdefault("uploads", {})
    options = [NO_PDF] + [str(p) for p in D.pdfs_in(".")] + [UPLOAD_PREFIX + n for n in uploads]
    pick_key = f"pdf_pick::{run.doc_id}"
    up_key = f"pdf_up::{run.doc_id}"

    def on_upload() -> None:
        f = st.session_state.get(up_key)
        if f is not None:
            uploads[f.name] = f.getvalue()
            remembered[run.doc_id] = UPLOAD_PREFIX + f.name
            st.session_state[pick_key] = UPLOAD_PREFIX + f.name

    if st.session_state.get(pick_key) not in options:
        st.session_state[pick_key] = remembered.get(run.doc_id) if remembered.get(run.doc_id) in options else NO_PDF
    choice = st.sidebar.selectbox("PDF for this run", options, key=pick_key)
    st.sidebar.file_uploader("or upload one", type=["pdf"], key=up_key, on_change=on_upload)
    if choice == NO_PDF:
        remembered.pop(run.doc_id, None)
        return None, ""
    remembered[run.doc_id] = choice
    if choice.startswith(UPLOAD_PREFIX):
        name = choice.removeprefix(UPLOAD_PREFIX)
        return uploads[name], name
    return choice, Path(choice).name


# --- tabs -----------------------------------------------------------------------------


def _table(rows: list[dict], columns: list[str], empty: str = "None.") -> None:
    if rows:
        st.dataframe(pd.DataFrame(rows, columns=columns), hide_index=True, width="stretch")
    else:
        st.caption(empty)


def _view_picker(run: D.Run, key: str, default: str) -> str:
    """Bid / After award switch (REVIEW.md, "Before the bid and after award")."""
    view = st.segmented_control(
        "View", D.VIEWS, default=default, key=f"{key}::{_key(str(run.path))}",
        help="Bid: what to know, decide and submit before the deadline, plus after-award obligations that "
        "carry a risk or an amount to price. After award: every obligation of the winning bidder.",
    ) or default
    if not any(D.is_post_award(r) for r in run.records):
        st.caption("This run marks no fact as post-award (runs made before 2026-11-18 do not), so Bid shows everything.")
    return view


def tab_summary(run: D.Run) -> None:
    """Six sections a bid manager reads first: who is buying, the dates, how to submit,
    whether we may bid, how proposals are scored, and what to ask the buyer. Each is a
    short summary in fixed rows, with the facts it was written from folded underneath;
    the calendar is a table of the dates themselves. Everything here is built from
    the stored result; opening the screen calls no model."""
    rep = run.report or {}
    # Runs stored before every section had a summary have the buyer one only, or none.
    summaries = rep.get("summaries") or ({"buyer": rep["buyer_brief"]} if rep.get("buyer_brief") else {})
    o = D.overview(run.records, summaries)
    sm = o["summary"]
    st.html(S.buyer_card(o["buyer"], o["buyer_facts"]))
    # Rows of two, in the order a bid is worked: when and how to submit, then whether
    # we may bid and how we are scored, then what to ask the buyer.
    left, right = st.columns(2, gap="medium")
    left.html(S.calendar_card(o["calendar"]))
    right.html(S.summary_card("Submission instructions", "S", sm["submission"], [("", o["submission"])]))
    left, right = st.columns(2, gap="medium")
    left.html(S.summary_card("Go/no-go gates", "G", sm["gates"], [
        ("To be allowed to bid", o["gates"]), ("What gets a proposal rejected", o["disqualifiers"]),
    ]))
    right.html(S.summary_card("Scoring criteria", "E", sm["scoring"], [("", o["scoring"])]))
    st.html(S.summary_card("Clarifications", "Q", sm["questions"], [
        ("The RFP contradicts itself", o["contradictions"]), ("Unclear, ask the buyer", o["unclear"]),
    ], note="Points to raise with the buyer before the question deadline."))


PAGE_SIZES = (15, 30, 60)


def _uid(r: dict) -> str:
    """Identity of a fact inside one run. Not fact_id alone: files not written by this
    pipeline may repeat it."""
    return f"{r['fact_id']}-{_key(r['category'], r['text'], [c['id'] for c in r['citations']])}"


_BADGE = {  # Streamlit's badge colours, nearest to the category colours in style.py
    "B": "gray", "C": "violet", "G": "green", "X": "red", "D": "blue", "S": "green", "E": "orange", "R": "violet",
    "Q": "red",
}
_FLAG_BADGE = {"mandatory": "violet", "risk": "red", "unclear": "orange", "post-award": "green"}


def _fact_label(r: dict, stated: int = 1) -> str:
    """The card's content as a button label: a row of badges, then the fact. A label is
    Markdown, so every piece of text from the PDF or the model is escaped."""
    def badge(text: str, colour: str) -> str:
        return f":{colour}-badge[{_md_escape(text)}]"

    code = r["category"]
    parts = [badge(CATEGORIES.get(code, code), _BADGE.get(code, "gray"))]
    if r.get("also"):
        parts.append(badge("also " + CATEGORIES.get(r["also"], r["also"]), _BADGE.get(r["also"], "gray")))
    if D.is_split(r):
        parts.append(badge("split vote " + r["agreement"], "orange"))
    if r["status"] != "valid":
        parts.append(badge(r["status"].replace("_", " "), "orange" if r["status"] == "needs_review" else "red"))
    parts += [badge(f, _FLAG_BADGE.get(f, "gray")) for f in r["flags"]]
    if stated > 1:
        parts.append(badge(f"stated {stated} times", "gray"))
    pages = "; ".join(dict.fromkeys(c["page_label"] for c in r["citations"] if c["page_label"]))
    if pages:
        parts.append(badge("p. " + pages, "gray"))
    return " ".join(parts) + "  \n" + _md_escape(" ".join(r["text"].split()))


def _select_fact(sel_key: str, fid: str) -> None:
    st.session_state[sel_key] = fid


def tab_facts(run: D.Run, pdf: str | bytes | None) -> None:
    """A reading list on the left, the selected fact and its page on the right.

    The list is cards, not a grid: a fact is a sentence, and a grid cuts it off. The
    right column stays in place while the list scrolls (style.py, .fx-sticky).
    """
    rk = _key(str(run.path))
    sel_key = f"f_sel::{rk}"
    top = st.columns([4, 6, 2], vertical_alignment="bottom")
    with top[0]:
        view = _view_picker(run, "f_view", "All")
    query = top[1].text_input(
        "Search", key=f"f_q::{rk}", placeholder="Search the facts and the text they cite",
        label_visibility="collapsed", icon=":material/search:",
    )
    with top[2].popover("More filters", width="stretch"):
        statuses = st.multiselect("Status", list(D.STATUSES), default=list(D.STATUSES), key=f"f_status::{rk}")
        flags = st.multiselect("Flags (any)", list(FLAGS), key=f"f_flags::{rk}")
        pages = None
        if run.pages > 1:
            rng = st.slider("Pages", 1, run.pages, (1, run.pages), key=f"f_pages::{rk}")
            if tuple(rng) != (1, run.pages):
                pages = tuple(rng)
        split_only = st.checkbox(
            "Split votes only", key=f"f_split::{rk}",
            help="Facts whose labelling votes did not all agree on the code.",
        )
        size = st.radio("Facts per page", PAGE_SIZES, horizontal=True, key=f"f_size::{rk}")

    # Type chips carry the count each type has under the other filters; none chosen = all.
    others = D.filter_facts(run.records, None, statuses, flags, query, pages, view, split_only)
    n_by = Counter(r["category"] for r in others)
    codes = [c for c in CATEGORIES if n_by[c]] + sorted(c for c in n_by if c not in CATEGORIES)
    cats = st.pills(
        "Type", codes, selection_mode="multi", key=f"f_cat::{rk}", label_visibility="collapsed",
        format_func=lambda c: f"{CATEGORIES.get(c, c).capitalize()}  {n_by[c]}",
    ) or []
    rows = D.document_order([r for r in others if not cats or r["category"] in cats])

    # The list shows items: a fact, a point stated in several places (once), or a list
    # of sibling facts (one card, its items inside). Paging counts items.
    all_items = D.items(rows)
    page_key = f"f_page::{_key(rk, cats, statuses, flags, query, pages, view, size, split_only)}"
    n_pages = max(1, -(-len(all_items) // size))
    page = min(st.session_state.get(page_key, 1), n_pages)
    shown = all_items[(page - 1) * size : page * size]
    ids = [_uid(r) for r in rows]
    if st.session_state.get(sel_key) not in ids:
        st.session_state[sel_key] = _uid(shown[0].first) if shown else None
    selected = st.session_state[sel_key]
    rep_of = {_uid(f): D.merged(it) for it in all_items if it.kind == "same" for f in it.facts}

    def fact_line(r: dict, shown_as: dict | None = None, stated: int = 1) -> None:
        """One fact as a card. The card is the button: clicking it opens the fact. The key
        carries the state and the category, which is what the stylesheet colours it by
        (style.py, "st-key-fact")."""
        uid = _uid(r)
        on = uid == selected or (stated > 1 and selected in rep_of and rep_of[selected]["fact_id"] == r["fact_id"])
        code = r["category"] if r["category"] in CATEGORIES else "Z"
        st.button(
            _fact_label(shown_as or r, stated), key=f"fact-{'on' if on else 'off'}-{code}-{rk}-{uid}",
            width="stretch", on_click=_select_fact, args=(sel_key, uid),
        )

    left, right = st.columns([11, 10], gap="medium")
    with left:
        bar = st.columns([6, 3], vertical_alignment="center")
        grouped = len(rows) - len(all_items)
        bar[0].text(f"{len(rows)} of {len(run.records)} facts" + (f", shown as {len(all_items)} items" if grouped else ""))
        bar[1].download_button(
            "Download CSV", D.to_csv(rows), file_name=D.csv_name(run.doc_id, run.run_id),
            mime="text/csv", icon=":material/download:", width="stretch",
        )
        if not rows:
            st.info("No fact matches these filters.")
        for it in shown:
            if it.kind == "fact":
                fact_line(it.first)
            elif it.kind == "same":
                fact_line(it.first, D.merged(it), stated=len(it.facts))
            else:
                st.html(S.group_row(it.title, it.first["category"], len(it.facts), it.pages()))
                inside = any(_uid(f) == selected for f in it.facts)
                with st.expander(f"Show the {len(it.facts)} items", expanded=inside):
                    for f in it.facts:
                        fact_line(f)
        if n_pages > 1:
            nav = st.columns([2, 5, 2], vertical_alignment="center")
            if nav[0].button("Previous", disabled=page <= 1, key=f"{page_key}::prev", width="stretch"):
                st.session_state[page_key] = page - 1
                st.rerun()
            first = (page - 1) * size + 1
            nav[1].html(S.centered(f"{first}-{first + len(shown) - 1} of {len(all_items)}  ·  page {page} of {n_pages}"))
            if nav[2].button("Next", disabled=page >= n_pages, key=f"{page_key}::next", width="stretch"):
                st.session_state[page_key] = page + 1
                st.rerun()
    with right:
        st.html(S.STICKY)
        current = next((r for r in rows if _uid(r) == selected), None)
        if current is None:
            st.info("Select a fact to see its source")
            return
        # A point stated in several places opens with every place it is stated.
        fact_detail(run, rep_of.get(selected, current), pdf)


def fact_detail(run: D.Run, r: dict, pdf: str | bytes | None) -> None:
    st.html(S.fact_card(r))
    if r["problems"]:
        st.warning("Needs review:\n\n" + "\n\n".join("- " + _md_escape(p) for p in r["problems"]))
    if r["conflicts"]:
        by_id = {x["fact_id"]: x for x in run.records}
        st.html(S.list_card("Contradictions citing the same source", "Q", [
            {"text": by_id[f]["text"] if f in by_id else f + " (not in this run)", "page": ""} for f in r["conflicts"]
        ]))
    if r["unresolved_ids"]:
        st.warning(
            "The model cited IDs that are not in the document: "
            + _md_escape(", ".join(r["unresolved_ids"]))
        )
    st.html(S.citations(r["citations"]))

    on_pages = [c for c in r["citations"] if c["page"]]
    if not on_pages:
        return
    if pdf is None:
        st.info("No PDF attached: showing the cited text only. Pick or upload the PDF in the sidebar.")
        return
    pages = list(dict.fromkeys(c["page"] for c in on_pages))
    label = {c["page"]: c["page_label"] for c in on_pages}
    page = pages[0]
    if len(pages) > 1:
        page = st.selectbox(
            "Page", pages, format_func=lambda p: f"page {label[p]} (PDF page {p})",
            key=f"cite_page::{_key(str(run.path), r['fact_id'])}",
        )
    boxes = tuple(tuple(c["bbox"]) for c in on_pages if c["page"] == page and c["bbox"])
    try:
        with st.container(border=True):
            st.image(render_page(pdf, page, boxes), width="stretch")
    except Exception as e:  # wrong PDF picked, page out of range
        st.error(f"Could not render page {page} of this PDF: {e}")


def tab_report(run: D.Run, runs: list[D.RunRef]) -> None:
    rep = run.report
    if not rep:
        st.info("This run has no report.json.")
        _all_runs(runs)
        return
    calls = rep.get("calls") or []
    secs = rep.get("seconds") or {}
    by_status = Counter(x.get("status") for x in calls)
    failed = rep.get("failed_calls") or []
    # Runs made before incomplete calls were detected logged them as ok: find those by their missing votes.
    incomplete = rep.get("incomplete_calls") or []
    hit = rep.get("cache_hit_calls_2_to_n")
    st.html(S.stats([
        ("Total time", f"{secs.get('total', '-')} s", ", ".join(f"{k} {v} s" for k, v in secs.items() if k != "total"), ""),
        ("Output tokens", f"{rep.get('output_tokens', 0):,}" if isinstance(rep.get("output_tokens"), int) else "-", "reasoning included", ""),
        ("Cache hit", f"{hit:.0%}" if isinstance(hit, (int, float)) else "-", "input tokens of calls 2..n", ""),
        ("Calls", len(calls), ", ".join(f"{n} {k}" for k, n in by_status.items()), ""),
        ("Failed calls", len(failed), ", ".join(map(str, failed)) or "none", "bad" if failed else ""),
        ("Incomplete calls", len(incomplete), ", ".join(map(str, incomplete)) or "none", "warn" if incomplete else ""),
    ]))
    if incomplete or rep.get("units_unanswered_votes"):
        st.caption(
            f"{rep.get('units_unanswered_votes', 0)} label votes are missing: a call that answers for only some of its "
            "units is asked once more, and is listed as incomplete if it is still short. Those units were decided on "
            "fewer votes."
        )
    st.subheader("Calls")
    df = pd.DataFrame(
        [
            {"name": x.get("name"), "kind": x.get("kind"), "status": x.get("status"),
             "seconds": round(x.get("seconds") or 0, 2), "lines": x.get("lines"),
             "output tokens": (x.get("usage") or {}).get("output_tokens"), "retries": x.get("retries")}
            for x in calls
        ],
        columns=["name", "kind", "status", "seconds", "lines", "output tokens", "retries"],
    )
    event = st.dataframe(
        df, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
        key=f"calls_table::{_key(str(run.path))}",
    )
    sel = event.selection.rows
    if not sel or sel[0] >= len(calls):
        st.caption("Select a call to see its log and output.")
    else:
        call = calls[sel[0]]
        st.markdown("**Log**")
        st.code("\n".join(map(str, call.get("log") or [])) or "(empty)", language=None, wrap_lines=True)
        st.markdown("**Output**")
        st.code(call.get("output") or "(empty)", language=None, wrap_lines=True)
    _all_runs(runs)


def _all_runs(runs: list[D.RunRef]) -> None:
    """How long every run in the folder took, newest first."""
    st.subheader("All runs in this folder")
    st.caption(
        "Wall-clock seconds from the run report. Extract is the first round of calls; sweep and check is "
        "everything after it. A run with no report shows no timing."
    )
    st.dataframe(
        pd.DataFrame(D.runs_table(runs)), hide_index=True, width="stretch",
        column_config={
            "total s": st.column_config.NumberColumn("Total (s)", format="%.1f"),
            "extract s": st.column_config.NumberColumn("Extract (s)", format="%.1f"),
            "sweep and check s": st.column_config.NumberColumn("Sweep and check (s)", format="%.1f"),
            "output tokens": st.column_config.NumberColumn("Output tokens", format="localized"),
        },
    )


def tab_compare(runs: list[D.RunRef], current: D.Run) -> None:
    by_path = {str(r.path): r for r in runs}
    paths = list(by_path)
    if "cmp_a" not in st.session_state or st.session_state["cmp_a"] not in by_path:
        st.session_state["cmp_a"] = str(current.path) if str(current.path) in by_path else paths[0]
    fmt = lambda p: _run_label(by_path[p])  # noqa: E731
    c1, c2 = st.columns(2)
    a_path = c1.selectbox("Run A", paths, key="cmp_a", format_func=fmt)
    a_ref = by_path[a_path]
    run_a = load_run(a_path, a_ref.mtime)

    def doc_of(p: str) -> str:
        return by_path[p].doc_id or load_run(p, by_path[p].mtime).doc_id

    same_doc = [p for p in paths if p != a_path and doc_of(p) == run_a.doc_id]
    if not same_doc:
        c2.selectbox("Run B", ["(no other run of this document)"], disabled=True)
        return
    b_path = c2.selectbox("Run B", same_doc, key=f"cmp_b::{_key(a_path)}", format_func=fmt)
    run_b = load_run(b_path, by_path[b_path].mtime)
    r = compare_runs(run_a.records, run_b.records)
    pct = lambda v: f"{v:.0%}" if isinstance(v, (int, float)) else "-"  # noqa: E731
    st.html(S.stats([
        ("Same sentences cited", pct(r["id_agreement"]),
         f"{r['cited_both']} IDs in both, of {r['cited_ids'][0]} and {r['cited_ids'][1]}", ""),
        ("Same codes per sentence", pct(r["code_agreement"]), f"{r['same_codes']} of {r['cited_both']} shared IDs", ""),
        ("Same fact IDs", pct(r["fact_id_agreement"]), f"{r['same_fact_id']} facts, of {r['facts'][0]} and {r['facts'][1]}", ""),
    ]))
    st.caption(
        f"Exact figures: ID agreement {r['id_agreement']}, code agreement {r['code_agreement']}, "
        f"fact ID agreement {r['fact_id_agreement']}. Runs made before 2026-11-18 hashed the wording into "
        "fact_id, so their fact ID agreement is near zero whatever the runs contain."
    )
    st.subheader("Per category")
    _table(
        [{"code": c, "name": CATEGORIES.get(c, ""), "A": x["a"], "B": x["b"], "IDs in both": x["ids_both"]}
         for c, x in r["by_category"].items()],
        ["code", "name", "A", "B", "IDs in both"],
    )
    st.subheader("Code differences")
    _table(
        [{"IDs": n, "codes only in one run": x or "-", "codes only in the other": y or "-"}
         for (x, y), n in r["code_flips"]],
        ["IDs", "codes only in one run", "codes only in the other"], "No differences.",
    )
    st.subheader("Source IDs filed under different codes")
    _table(
        [{"ID": d["id"], "codes in A": d["codes_a"], "codes in B": d["codes_b"],
          "facts in A": d["facts_a"], "facts in B": d["facts_b"]} for d in D.code_differences(run_a.records, run_b.records)],
        ["ID", "codes in A", "codes in B", "facts in A", "facts in B"], "No differences.",
    )


def tab_new_run() -> None:
    msg = st.session_state.get("new_run_msg")
    if msg:
        st.success("Run finished.")
        st.text(f"{msg[0]}\nWritten to {msg[1]}")
    st.caption("Runs are written to runs/<doc_id>/<run_id>/ with facts.json, report.json and source.pdf.")
    source = st.radio("PDF", ["Pick from the working directory", "Upload"], horizontal=True, key="new_src")
    pdf_bytes, name = None, ""
    if source == "Upload":
        up = st.file_uploader("PDF file", type=["pdf"], key="new_up")
        if up is not None:
            pdf_bytes, name = up.getvalue(), up.name
    else:
        files = [str(p) for p in D.pdfs_in(".")]
        pick = st.selectbox("PDF file", ["(choose)"] + files, key="new_pick")
        if pick != "(choose)":
            pdf_bytes, name = Path(pick).read_bytes(), Path(pick).name
    deal_id = st.text_input("Deal ID", key="new_deal")
    stem = name.rsplit(".", 1)[0] if name else ""
    doc_id = st.text_input("Doc ID", value=stem, key=f"new_doc::{stem}")
    model = st.text_input("Model", value=os.environ.get("FACT_EXTRACTOR_MODEL", "gpt-6-luna"), key="new_model")
    votes = st.radio(
        "Votes per unit", [1, 3, 5], index=1, horizontal=True, key="new_votes",
        help="Each unit of the RFP is labelled this many times and the majority wins.",
    )

    stored = None
    if pdf_bytes is not None:
        try:
            rows, n_ids = plan_for(pdf_bytes, doc_id or stem or "doc", int(votes))
        except Exception as e:
            st.error(f"Could not read this PDF: {e}")
            pdf_bytes = None
        else:
            stored = D.stored_result(pdf_bytes, doc_id.strip()) if doc_id.strip() else None
            with st.expander(f"Planned calls: {sum(r['times'] for r in rows)} calls over {n_ids} units, sent together"):
                _table(rows, ["call", "times", "units", "pages"])
    if stored is not None:
        st.success(
            f"This PDF already has a stored result ({stored.meta.get('facts')} facts, "
            f"{_md_escape(str(stored.meta.get('created')))}). Opening it calls no model and shows the same facts."
        )
        if st.button("Open the stored result", type="primary", key="new_open"):
            _open_run(stored.facts_path, None)
    st.warning("Extracting calls the model and spends API tokens." + (" The stored result is kept." if stored else ""))
    confirmed = st.checkbox("I understand this spends API tokens", key="new_confirm")
    has_key = bool(os.environ.get("OPENAI_API_KEY"))
    if not has_key:
        st.error("OPENAI\\_API\\_KEY is not set (in the environment or .env), so no run can start.")
    missing = [w for w, ok in (("a PDF", pdf_bytes is not None), ("a deal ID", deal_id.strip()), ("a doc ID", doc_id.strip())) if not ok]
    if missing:
        st.caption("Still needed: " + ", ".join(missing) + ".")
    start = st.button(
        "Extract again" if stored else "Start extraction", type="secondary" if stored else "primary",
        disabled=not (confirmed and has_key and not missing), key="new_start",
    )
    if start:
        with st.spinner("Extracting... this takes about half a minute on a 50-page RFP."):
            try:
                facts_path, report, _ = D.run_extraction(
                    pdf_bytes, deal_id=deal_id.strip(), doc_id=doc_id.strip(),
                    model=model.strip() or None, votes=int(votes), refresh=True,
                )
            except Exception as e:
                st.error(f"The run failed and nothing was written: {type(e).__name__}: {e}")
                return
        _open_run(facts_path, D.result_line(report))


def _open_run(facts_path: Path, message: str | None) -> None:
    """Select a run under runs/ in the sidebar on the next rerun."""
    if message:
        st.session_state["new_run_msg"] = (message, str(facts_path.parent))
    st.session_state["_pending_run"] = str(facts_path)
    find_runs.clear()
    st.rerun()


def main() -> None:
    st.set_page_config(page_title="RFP fact review", page_icon=":material/fact_check:", layout="wide")
    st.html(S.CSS)
    load_env()
    _apply_pending()
    runs, run, pdf, pdf_name = sidebar()
    if pdf_name:
        st.sidebar.caption(f"Showing pages from {pdf_name}")
    if run is not None:
        st.html(S.header(run.doc_id, run.run_id, run.pages, len(run.records), pdf_name, st.session_state.get("_took", "")))
    else:
        st.html(S.header("RFP fact review", "", 0, 0, "", ""))
    names = ["Summary", "Facts", "Run report", "Compare runs", "New run"]
    tabs = st.tabs(names)
    if run is None:
        for t in tabs[:4]:
            t.info(f"No run open. There are no runs in {RUNS}/ yet; start one in the New run tab.")
    else:
        with tabs[0]:
            tab_summary(run)
        with tabs[1]:
            tab_facts(run, pdf)
        with tabs[2]:
            tab_report(run, runs)
        with tabs[3]:
            tab_compare(runs, run)
    with tabs[4]:
        tab_new_run()


main()
