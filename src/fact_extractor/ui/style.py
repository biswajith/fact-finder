"""Look of the review app: one stylesheet and the few HTML fragments Streamlit has no
widget for (stat tiles, list cards, the fact card, citations, category bars).

Every piece of text that comes from a PDF, a model or a file name goes through `esc`
before it enters a fragment, so it is always shown as text (UI_SPEC.md section 9).
No Streamlit import here.
"""

from __future__ import annotations

from html import escape as esc

from fact_extractor.models import CATEGORIES

# One colour per category, used for pills, card accents and bars.
COLORS = {
    "B": "#64748b", "C": "#7c3aed", "G": "#15803d", "X": "#dc2626", "D": "#2563eb",
    "S": "#0d9488", "E": "#b45309", "R": "#4f46e5", "Q": "#be185d",
}
FLAG_COLORS = {
    "mandatory": "#4f46e5", "desirable": "#64748b", "risk": "#dc2626", "unclear": "#b45309",
    "replaced": "#64748b", "post-award": "#0d9488",
}
STATUS_COLORS = {"valid": "#15803d", "needs_review": "#b45309", "conflict": "#dc2626"}
SHOWN = 8  # items a list card shows before "show all"

CSS = """<style>
:root { --fx-ink:#1b2130; --fx-muted:#6b7385; --fx-line:#e5e8ef; --fx-card:#ffffff; --fx-bg:#f5f6f9; --fx-accent:#3b5bdb; }
.stApp { background: var(--fx-bg); }
.block-container { padding-top: 3.6rem; padding-bottom: 3rem; max-width: 1500px; }
html, body, .stApp, .stApp p, .stApp label, .stApp input, .stApp button {
  font-family: Inter, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; }
section[data-testid="stSidebar"] { background: #ffffff; border-right: 1px solid var(--fx-line); }
div[data-testid="stText"] { font-family: inherit; color: var(--fx-muted); font-size: 0.85rem; }
button[data-baseweb="tab"] p { font-size: 0.95rem; font-weight: 600; }
div[data-testid="stDataFrame"] { border: 1px solid var(--fx-line); border-radius: 12px; overflow: hidden; background: #fff; }
div[data-testid="stImage"] img { border-radius: 6px; }

.fx-brand { display:flex; align-items:center; gap:.55rem; font-weight:700; font-size:1.05rem; color:var(--fx-ink); margin-bottom:.4rem; }
.fx-brand span { display:inline-grid; place-items:center; width:1.9rem; height:1.9rem; border-radius:8px; background:var(--fx-accent); color:#fff; font-size:.9rem; }
.fx-head { display:flex; flex-wrap:wrap; align-items:baseline; gap:.4rem 1rem; margin: 0 0 .2rem 0; }
.fx-head h1 { font-size:1.55rem; font-weight:700; color:var(--fx-ink); margin:0; padding:0; letter-spacing:-0.01em; }
.fx-head .fx-meta { color:var(--fx-muted); font-size:.88rem; }
.fx-head .fx-meta b { color:var(--fx-ink); font-weight:600; }

.fx-stats { display:grid; grid-template-columns:repeat(auto-fit, minmax(128px, 1fr)); gap:.75rem; margin:.4rem 0 .6rem; }
.fx-stat { background:var(--fx-card); border:1px solid var(--fx-line); border-radius:12px; padding:.8rem 1rem; box-shadow:0 1px 2px rgba(16,24,40,.04); }
.fx-stat .l { color:var(--fx-muted); font-size:.74rem; font-weight:600; text-transform:uppercase; letter-spacing:.05em; }
.fx-stat .v { color:var(--fx-ink); font-size:1.7rem; font-weight:700; line-height:1.25; font-variant-numeric:tabular-nums; }
.fx-stat .h { color:var(--fx-muted); font-size:.78rem; }
.fx-stat.warn { border-left:4px solid #d97706; } .fx-stat.warn .v { color:#b45309; }
.fx-stat.bad { border-left:4px solid #dc2626; } .fx-stat.bad .v { color:#dc2626; }

.fx-card { background:var(--fx-card); border:1px solid var(--fx-line); border-radius:12px; padding:1rem 1.1rem; margin-bottom:.9rem; box-shadow:0 1px 2px rgba(16,24,40,.04); border-top:3px solid var(--c, var(--fx-line)); }
.fx-card h3 { display:flex; align-items:center; gap:.5rem; margin:0 0 .5rem; padding:0; font-size:1rem; font-weight:700; color:var(--fx-ink); }
.fx-card h3 .n { background:color-mix(in srgb, var(--c, #64748b) 12%, white); color:var(--c, #64748b); border-radius:999px; padding:.05rem .55rem; font-size:.78rem; font-weight:700; }
.fx-card .note { color:var(--fx-muted); font-size:.82rem; margin:-.2rem 0 .5rem; }
.fx-card ul { list-style:none; margin:0; padding:0; }
.fx-card li { display:flex; justify-content:space-between; gap:.8rem; padding:.5rem 0; border-top:1px solid #f0f2f6; color:var(--fx-ink); font-size:.92rem; line-height:1.4; }
.fx-card li:first-child { border-top:0; }
.fx-card li .t { flex:1; }
.fx-card .empty { color:var(--fx-muted); font-size:.88rem; }
.fx-card details summary { cursor:pointer; color:var(--fx-accent); font-size:.85rem; font-weight:600; padding:.5rem 0 .1rem; }
.fx-pg { white-space:nowrap; color:var(--fx-muted); font-size:.78rem; background:#f2f4f8; border-radius:6px; padding:.1rem .45rem; align-self:flex-start; }
.fx-pill { display:inline-block; white-space:nowrap; border-radius:999px; padding:.12rem .6rem; font-size:.76rem; font-weight:600; background:color-mix(in srgb, var(--c) 12%, white); color:var(--c); margin-right:.3rem; }
.fx-pill.solid { background:var(--c); color:#fff; }

.fx-fact { background:var(--fx-card); border:1px solid var(--fx-line); border-left:4px solid var(--c); border-radius:12px; padding:1rem 1.2rem; margin-bottom:.9rem; box-shadow:0 1px 2px rgba(16,24,40,.04); }
.fx-fact .txt { color:var(--fx-ink); font-size:1.12rem; font-weight:600; line-height:1.45; margin:.6rem 0 .5rem; }
.fx-fact .meta { color:var(--fx-muted); font-size:.78rem; }
.fx-fact .note { color:var(--fx-ink); font-size:.88rem; margin-bottom:.4rem; }
.fx-cite { background:#fafbfc; border:1px solid var(--fx-line); border-radius:10px; padding:.7rem .9rem; margin-bottom:.6rem; }
.fx-cite .w { color:var(--fx-muted); font-size:.78rem; margin-bottom:.3rem; }
.fx-cite .w b { color:var(--fx-ink); }
.fx-cite .q { color:var(--fx-ink); font-size:.9rem; line-height:1.5; border-left:3px solid #f5c542; padding-left:.7rem; }
.fx-sec { color:var(--fx-muted); font-size:.74rem; font-weight:700; text-transform:uppercase; letter-spacing:.05em; margin:.2rem 0 .5rem; }

.fx-bars .row { display:grid; grid-template-columns: 190px 1fr 48px; align-items:center; gap:.7rem; padding:.28rem 0; font-size:.88rem; color:var(--fx-ink); }
.fx-bars .track { background:#f0f2f6; border-radius:999px; height:.6rem; overflow:hidden; }
.fx-bars .fill { background:var(--c); height:100%; border-radius:999px; }
.fx-bars .num { text-align:right; font-variant-numeric:tabular-nums; color:var(--fx-muted); }

.fx-row { background:var(--fx-card); border:1px solid var(--fx-line); border-left:4px solid var(--c); border-radius:10px; padding:.65rem .9rem; box-shadow:0 1px 2px rgba(16,24,40,.03); }
.fx-row.on { border-color:var(--fx-accent); border-left-color:var(--c); box-shadow:0 0 0 2px color-mix(in srgb, var(--fx-accent) 25%, white); background:#fbfcff; }
.fx-row .top { display:flex; justify-content:space-between; align-items:center; gap:.6rem; margin-bottom:.3rem; }
.fx-row .txt { color:var(--fx-ink); font-size:.95rem; line-height:1.45; }
.fx-row.fx-group { background:#fafbfc; border-style:dashed; border-left-style:solid; }
.fx-row.fx-group .txt { font-weight:600; }
div[class*="st-key-fact-"] button { display:block; width:100%; height:auto; min-height:0; text-align:left; white-space:normal; background:var(--fx-card); border:1px solid var(--fx-line); border-left:4px solid var(--c, #64748b); border-radius:10px; padding:.6rem .9rem; box-shadow:0 1px 2px rgba(16,24,40,.03); color:var(--fx-ink); cursor:pointer; }
div[class*="st-key-fact-"] button:hover { border-color:var(--fx-accent); border-left-color:var(--c, #64748b); background:#fbfcff; color:var(--fx-ink); }
div[class*="st-key-fact-"] button div, div[class*="st-key-fact-"] button p { display:block; text-align:left; width:100%; font-size:.95rem; line-height:1.5; font-weight:400; margin:0; white-space:normal; overflow:visible; text-overflow:clip; overflow-wrap:anywhere; }
div[class*="st-key-fact-on-"] button { border-color:var(--fx-accent); border-left-color:var(--c, #64748b); box-shadow:0 0 0 2px color-mix(in srgb, var(--fx-accent) 25%, white); background:#fbfcff; }
div[class*="-B-"][class*="st-key-fact-"] { --c:#64748b; } div[class*="-C-"][class*="st-key-fact-"] { --c:#7c3aed; }
div[class*="-G-"][class*="st-key-fact-"] { --c:#15803d; } div[class*="-X-"][class*="st-key-fact-"] { --c:#dc2626; }
div[class*="-D-"][class*="st-key-fact-"] { --c:#2563eb; } div[class*="-S-"][class*="st-key-fact-"] { --c:#0d9488; }
div[class*="-E-"][class*="st-key-fact-"] { --c:#b45309; } div[class*="-R-"][class*="st-key-fact-"] { --c:#4f46e5; }
div[class*="-Q-"][class*="st-key-fact-"] { --c:#be185d; }
.fx-kv { display:grid; grid-template-columns: minmax(110px, 170px) 1fr auto; gap:.1rem 1rem; }
.fx-kv > div { padding:.55rem 0; border-top:1px solid #f0f2f6; font-size:.94rem; line-height:1.45; color:var(--fx-ink); }
.fx-kv > div:nth-child(-n+3) { border-top:0; }
.fx-kv .k { color:var(--fx-muted); font-weight:600; font-size:.82rem; text-transform:uppercase; letter-spacing:.04em; padding-top:.7rem; }
.fx-kv .none { color:var(--fx-muted); font-style:italic; }
.fx-card h4 { margin:.9rem 0 .2rem; padding:0; font-size:.78rem; font-weight:700; color:var(--fx-muted); text-transform:uppercase; letter-spacing:.05em; }
.fx-card li.sub { padding-left:1rem; font-size:.88rem; color:#3b4252; border-top:0; padding-top:.15rem; padding-bottom:.15rem; }
.fx-card li.head { font-weight:600; }
.fx-cal { display:grid; grid-template-columns: 150px 1fr auto; gap:0 1rem; }
.fx-cal > div { padding:.55rem 0; border-top:1px solid #f0f2f6; font-size:.94rem; line-height:1.45; color:var(--fx-ink); }
.fx-cal > div:nth-child(-n+3) { border-top:0; }
.fx-cal .d { font-weight:700; font-variant-numeric:tabular-nums; white-space:nowrap; }
.fx-cal .d small { display:block; font-weight:400; color:var(--fx-muted); font-size:.8rem; }
@media (max-width: 760px) { .fx-kv, .fx-cal { grid-template-columns: 1fr; } .fx-kv .k { padding-bottom:0; } }
.fx-center { text-align:center; color:var(--fx-muted); font-size:.85rem; }
div[data-testid="stColumn"]:has(.fx-sticky) { position:sticky; top:3.6rem; align-self:flex-start; max-height:calc(100vh - 4.2rem); overflow-y:auto; padding-right:.3rem; }
div[data-testid="stElementContainer"]:has(.fx-row) + div, div[data-testid="stHorizontalBlock"]:has(.fx-row) { margin-bottom:-.35rem; }
</style>"""

STICKY = '<span class="fx-sticky"></span>'  # marks the column that stays in place
BRAND = '<div class="fx-brand"><span>&#10003;</span>RFP fact review</div>'


def pill(text: str, color: str, solid: bool = False) -> str:
    return f'<span class="fx-pill{" solid" if solid else ""}" style="--c:{color}">{esc(str(text))}</span>'


def header(doc_id: str, run_id: str, pages: int, facts: int, pdf_name: str, took: str = "") -> str:
    meta = []
    if run_id:
        meta.append(f"run <b>{esc(run_id)}</b>")
    if pages:
        meta.append(f"<b>{pages}</b> pages")
    if facts:
        meta.append(f"<b>{facts}</b> facts")
    if took:
        meta.append(f"extracted in <b>{esc(took)}</b>")
    if pdf_name:
        meta.append(esc(pdf_name))
    return f'<div class="fx-head"><h1>{esc(doc_id)}</h1><div class="fx-meta">{" &middot; ".join(meta)}</div></div>'


def stats(items: list[tuple]) -> str:
    """Tiles of (label, value, hint, tone); tone is "", "warn" or "bad"."""
    tiles = "".join(
        f'<div class="fx-stat {esc(tone)}"><div class="l">{esc(str(label))}</div>'
        f'<div class="v">{esc(str(value))}</div><div class="h">{esc(str(hint))}</div></div>'
        for label, value, hint, tone in items
    )
    return f'<div class="fx-stats">{tiles}</div>'


def _item(row: dict, show_code: bool) -> str:
    code = row.get("category", "")
    lead = pill(CATEGORIES.get(code, code), COLORS.get(code, "#64748b")) if show_code and code else ""
    flags = "".join(pill(f, FLAG_COLORS.get(f, "#64748b")) for f in str(row.get("flags", "")).split(", ") if f)
    page = row.get("page") or ""
    chip = f'<span class="fx-pg">p. {esc(str(page))}</span>' if page else ""
    return f'<li><span class="t">{lead}{flags}{esc(row["text"])}</span>{chip}</li>'


def list_card(title: str, code: str, rows: list[dict], *, show_code: bool = False, note: str = "") -> str:
    color = COLORS.get(code, "#64748b")
    head = f'<h3>{esc(title)}<span class="n">{len(rows)}</span></h3>'
    if note:
        head += f'<div class="note">{esc(note)}</div>'
    if not rows:
        body = '<div class="empty">None found in this view.</div>'
    else:
        body = "<ul>" + "".join(_item(r, show_code) for r in rows[:SHOWN]) + "</ul>"
        if len(rows) > SHOWN:
            rest = "".join(_item(r, show_code) for r in rows[SHOWN:])
            body += f"<details><summary>Show all {len(rows)}</summary><ul>{rest}</ul></details>"
    return f'<div class="fx-card" style="--c:{color}">{head}{body}</div>'


def fact_card(r: dict) -> str:
    code = r["category"]
    color = COLORS.get(code, "#64748b")
    pills = pill(CATEGORIES.get(code, code), color, solid=True) + _vote_pills(r)
    if r["status"] != "valid":
        pills += pill(r["status"].replace("_", " "), STATUS_COLORS.get(r["status"], "#64748b"))
    pills += "".join(pill(f, FLAG_COLORS.get(f, "#64748b")) for f in r["flags"])
    note = f'<div class="note">Note: {esc(r["note"])}</div>' if r["note"] else ""
    meta = f'{esc(str(r["fact_id"]))} &middot; from call {esc(r["source_call"] or "-")} &middot; status {esc(r["status"])}'
    if r.get("votes"):
        meta += " &middot; votes " + esc(" ".join(r["votes"]))
    if r.get("text_from") == "source":
        meta += " &middot; shown in the RFP's own words"
    return (
        f'<div class="fx-fact" style="--c:{color}"><div>{pills}</div>'
        f'<div class="txt">{esc(r["text"])}</div>{note}<div class="meta">{meta}</div></div>'
    )


def citations(cites: list[dict]) -> str:
    if not cites:
        return '<div class="fx-sec">Source</div><div class="fx-cite"><div class="w">No citations.</div></div>'
    out = [f'<div class="fx-sec">Source in the RFP ({len(cites)})</div>']
    for c in cites:
        where = f'<b>Page {esc(str(c["page_label"] or "?"))}</b>'
        if c["section"]:
            where += f' &middot; {esc(c["section"])}'
        where += f' &middot; {esc(c["id"])}' + ("" if c["bbox"] else " &middot; no position")
        out.append(f'<div class="fx-cite"><div class="w">{where}</div><div class="q">{esc(c["text"])}</div></div>')
    return "".join(out)


def bars(title: str, by_label: dict[str, int]) -> str:
    """Horizontal bars; labels are "R - requirement" style, the code picks the colour."""
    if not by_label:
        return f'<div class="fx-card"><h3>{esc(title)}</h3><div class="empty">No facts.</div></div>'
    top = max(by_label.values()) or 1
    rows = ""
    for label, n in sorted(by_label.items(), key=lambda kv: -kv[1]):
        code = label.split(" ", 1)[0]
        name = label.split(" - ", 1)[1] if " - " in label else label
        rows += (
            f'<div class="row"><span>{esc(name.capitalize())}</span><div class="track">'
            f'<div class="fill" style="--c:{COLORS.get(code, "#64748b")};width:{100 * n / top:.1f}%"></div></div>'
            f'<span class="num">{n}</span></div>'
        )
    return f'<div class="fx-card fx-bars"><h3>{esc(title)}</h3>{rows}</div>'


def _vote_pills(r: dict) -> str:
    """A second code, and a marker when the labelling votes were split."""
    out = ""
    if r.get("also"):
        out += pill("also " + CATEGORIES.get(r["also"], r["also"]), COLORS.get(r["also"], "#64748b"))
    if len(set(r.get("votes") or [])) > 1:
        out += pill("split vote " + (r.get("agreement") or ""), "#b45309")
    return out


def fact_row(r: dict, selected: bool, stated: int = 1) -> str:
    """One fact in the reading list: type and flags, the full sentence, the page."""
    code = r["category"]
    color = COLORS.get(code, "#64748b")
    pills = pill(CATEGORIES.get(code, code), color) + _vote_pills(r)
    if r["status"] != "valid":
        pills += pill(r["status"].replace("_", " "), STATUS_COLORS.get(r["status"], "#64748b"))
    pills += "".join(pill(f, FLAG_COLORS.get(f, "#64748b")) for f in r["flags"])
    if stated > 1:
        pills += pill(f"stated {stated} times", "#64748b")
    pages = "; ".join(dict.fromkeys(c["page_label"] for c in r["citations"] if c["page_label"]))
    chip = f'<span class="fx-pg">p. {esc(pages)}</span>' if pages else ""
    return (
        f'<div class="fx-row{" on" if selected else ""}" style="--c:{color}"><div class="top"><span>{pills}</span>{chip}</div>'
        f'<div class="txt">{esc(r["text"])}</div></div>'
    )


def group_row(title: str, code: str, count: int, pages: str) -> str:
    """The head of a list group in the reading list; its items sit in the expander below."""
    color = COLORS.get(code, "#64748b")
    chip = f'<span class="fx-pg">p. {esc(pages)}</span>' if pages else ""
    return (
        f'<div class="fx-row fx-group" style="--c:{color}"><div class="top"><span>'
        f'{pill(CATEGORIES.get(code, code), color)}{pill(f"{count} items", color, solid=True)}</span>{chip}</div>'
        f'<div class="txt">{esc(title)}</div></div>'
    )


def centered(text: str) -> str:
    return f'<div class="fx-center">{esc(text)}</div>'


# --- Summary screen ----------------------------------------------------------------------


def _chip(page: str) -> str:
    return f'<span class="fx-pg">p. {esc(str(page))}</span>' if page else ""


def _lines(entries: list[dict], limit: int = SHOWN) -> str:
    """Entries as list lines; a list entry shows its title, then its items indented."""
    def one(e: dict) -> str:
        if not e.get("children"):
            return f'<li><span class="t">{esc(e["text"])}</span>{_chip(e["page"])}</li>'
        head = f'<li class="head"><span class="t">{esc(e["text"])} ({len(e["children"])})</span>{_chip(e["page"])}</li>'
        return head + "".join(f'<li class="sub"><span class="t">{esc(c["text"])}</span></li>' for c in e["children"])

    if not entries:
        return '<div class="empty">None found.</div>'
    body = "<ul>" + "".join(one(e) for e in entries[:limit]) + "</ul>"
    if len(entries) > limit:
        body += f'<details><summary>Show all {len(entries)}</summary><ul>{"".join(one(e) for e in entries[limit:])}</ul></details>'
    return body


def section_card(title: str, code: str, parts: list[tuple[str, list[dict]]], note: str = "") -> str:
    """A Summary card with one or more titled parts, each a list of entries."""
    color = COLORS.get(code, "#64748b")
    total = sum(len(e) for _, e in parts)
    out = f'<h3>{esc(title)}<span class="n">{total}</span></h3>'
    if note:
        out += f'<div class="note">{esc(note)}</div>'
    for heading, entries in parts:
        if heading:
            out += f"<h4>{esc(heading)} ({len(entries)})</h4>"
        out += _lines(entries)
    return f'<div class="fx-card" style="--c:{color}">{out}</div>'


def _kv(rows: list[dict]) -> str:
    cells = ""
    for r in rows:
        value = esc(r["text"]) if r["text"] else '<span class="none">Not stated in the RFP</span>'
        cells += f'<div class="k">{esc(r["row"])}</div><div>{value}</div><div>{_chip(r["page"])}</div>'
    return f'<div class="fx-kv">{cells}</div>'


def summary_card(title: str, code: str, rows: list[dict], parts: list[tuple[str, list[dict]]], note: str = "") -> str:
    """A Summary section: its summary rows, and the facts behind them folded underneath.
    A run with no summary for the section shows the facts as lists."""
    if not rows:
        return section_card(title, code, parts, note)
    color = COLORS.get(code, "#64748b")
    total = sum(len(e) for _, e in parts)
    behind = ""
    for heading, entries in parts:
        if entries:
            behind += (f"<h4>{esc(heading)} ({len(entries)})</h4>" if heading else "") + _lines(entries, limit=10**6)
    details = f"<details><summary>Show the {total} facts behind this</summary>{behind}</details>" if total else ""
    return f'<div class="fx-card" style="--c:{color}"><h3>{esc(title)}</h3>{_kv(rows)}{details}</div>'


def buyer_card(rows: list[dict], fallback: list[dict]) -> str:
    """The buyer brief as label and value rows; the buyer facts as a list when there is no brief."""
    color = COLORS["B"]
    if not rows:
        return section_card("Buyer information", "B", [("", fallback)],
                            note="This run has no buyer brief; these are its buyer facts.")
    cells = ""
    for r in rows:
        value = esc(r["text"]) if r["text"] else '<span class="none">Not stated in the RFP</span>'
        cells += f'<div class="k">{esc(r["row"])}</div><div>{value}</div><div>{_chip(r["page"])}</div>'
    return f'<div class="fx-card" style="--c:{color}"><h3>Buyer information</h3><div class="fx-kv">{cells}</div></div>'


def calendar_card(cal: dict) -> str:
    color = COLORS["D"]
    n = len(cal["dated"]) + len(cal["undated"])
    out = f'<h3>Calendar<span class="n">{n}</span></h3>'
    if cal["dated"]:
        cells = "".join(
            f'<div class="d">{esc(d["label"])}{"<small>" + esc(d["time"]) + "</small>" if d["time"] else ""}</div>'
            f'<div>{esc(d["text"])}</div><div>{_chip(d["page"])}</div>'
            for d in cal["dated"]
        )
        out += f'<div class="fx-cal">{cells}</div>'
    elif not cal["undated"]:
        out += '<div class="empty">No dates found.</div>'
    if cal["undated"]:
        out += f'<h4>No fixed date ({len(cal["undated"])})</h4>' + _lines(
            [{"text": u["text"], "page": u["page"], "children": []} for u in cal["undated"]])
    return f'<div class="fx-card" style="--c:{color}">{out}</div>'
