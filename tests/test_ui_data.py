"""The review app's non-Streamlit half (UI_SPEC.md section 10). No model call."""

import csv
import io
import json

import pymupdf
import pytest
from conftest import ScriptedClient

from fact_extractor.pipeline import Config
from fact_extractor.ui import data as D


def fact(cat, text, cites=(), flags=(), status="valid", **kw):
    return {
        "fact_id": kw.pop("fact_id", f"f_{text[:6]}"), "doc_id": "rfp-1", "run_id": "run_x",
        "category": cat, "text": text, "flags": list(flags), "status": status, "note": kw.pop("note", ""),
        "source_call": kw.pop("source_call", "A"), "problems": kw.pop("problems", []),
        "conflicts": kw.pop("conflicts", []), "unresolved_ids": [],
        "citations": [
            {"id": i, "page": p, "page_label": str(p), "section": f"S{p}", "text": t, "bbox": [10, 10, 100, 20]}
            for i, p, t in cites
        ],
    }


RECORDS = D.normalize([
    fact("R", "Vendor must keep 24/7 support", [("p3.10", 3, "The vendor must provide support.")],
         flags=["mandatory"], problems=["number 24 not in cited text"], status="needs_review"),
    fact("D", "Proposals due 2027-03-03", [("p1.2", 1, "Proposals are due March 3, 2027.")]),
    fact("C", "Unlimited liability", [("p3.4", 3, "Liability is unlimited.")], flags=["risk"]),
    fact("Q", "Due date 2027-03-03 vs 2027-03-05",
         [("p1.2", 1, "Proposals are due March 3, 2027."), ("p5.1", 5, "Due March 5, 2027.")], status="valid"),
    fact("D", "Due 2027-03-05", [("p5.1", 5, "Due March 5, 2027.")], status="conflict", flags=["unclear"]),
    fact("R", "Heading fact", [("p3.h1", 3, "3. Requirements")]),
    fact("G", "Must be licensed in NY", [("p2.t1r2", 2, "License: NY | Required: Yes")]),
    fact("X", "Late proposals rejected", [("p3.4", 3, "Liability is unlimited.")]),
])


def test_normalize_fills_missing_fields():
    (r,) = D.normalize([{"category": "B", "text": "t", "citations": [{"id": "p1.1", "page": 1}]}])
    assert r["flags"] == [] and r["status"] == "valid" and r["fact_id"] == "1" and r["note"] == ""
    assert r["citations"][0]["page_label"] == "1" and r["citations"][0]["bbox"] is None


def texts(rs):
    return [r["text"] for r in rs]


def test_filter_each_alone():
    assert set(texts(D.filter_facts(RECORDS, categories=["D"]))) == {"Proposals due 2027-03-03", "Due 2027-03-05"}
    assert texts(D.filter_facts(RECORDS, statuses=["needs_review"])) == ["Vendor must keep 24/7 support"]
    assert set(texts(D.filter_facts(RECORDS, flags=["risk", "unclear"]))) == {"Unlimited liability", "Due 2027-03-05"}
    # search covers the cited text, case-insensitively
    assert set(texts(D.filter_facts(RECORDS, query="LIABILITY"))) == {"Unlimited liability", "Late proposals rejected"}
    assert set(texts(D.filter_facts(RECORDS, pages=(5, 5)))) == {"Due date 2027-03-03 vs 2027-03-05", "Due 2027-03-05"}
    assert len(D.filter_facts(RECORDS)) == len(RECORDS)
    assert D.filter_facts(RECORDS, categories=[]) == RECORDS  # empty means no filter


def test_filter_combined():
    got = D.filter_facts(RECORDS, categories=["D", "Q"], statuses=["valid"], query="due", pages=(1, 1))
    assert set(texts(got)) == {"Proposals due 2027-03-03", "Due date 2027-03-03 vs 2027-03-05"}
    assert D.filter_facts(RECORDS, categories=["R"], flags=["risk"]) == []


def test_document_order():
    order = texts(D.document_order(RECORDS))
    assert order.index("Proposals due 2027-03-03") < order.index("Must be licensed in NY")
    # p3.h1 before p3.4 before p3.10 (numeric, not text order)
    assert order.index("Heading fact") < order.index("Unlimited liability") < order.index("Vendor must keep 24/7 support")
    uncited = D.normalize([{"category": "R", "text": "none", "citations": []}])
    assert texts(D.document_order(uncited + RECORDS))[-1] == "none"
    assert D.id_position("p12.4") < D.id_position("p12.10") < D.id_position("p12.h10") < D.id_position("p12.t10r1")


def test_summary_counts_and_lists():
    s = D.summary(RECORDS)
    assert s["facts"] == 8
    assert s["counts"] == {"needs review": 1, "conflicts": 1, "risk flags": 1, "mandatory": 1, "unclear": 1, "after award": 0, "split votes": 0}
    assert texts(s["dates"]) == ["Proposals due 2027-03-03", "Due 2027-03-05"]
    assert texts(s["gates"]) == ["Must be licensed in NY"] and texts(s["disqualifiers"]) == ["Late proposals rejected"]
    assert texts(s["contract_risks"]) == ["Unlimited liability"]
    assert s["contradictions"] == [{"text": "Due date 2027-03-03 vs 2027-03-05", "pages": "1 vs 5"}]
    assert s["by_category"]["R - requirement"] == 2


def test_summary_of_no_facts():
    s = D.summary([])
    assert s["facts"] == 0 and s["dates"] == [] and s["by_category"] == {}


def test_csv_columns_and_encoding():
    raw = D.to_csv(RECORDS[:1] + [D.normalize([fact("B", "Café — Zürich", [("p1.1", 1, "a"), ("p2.1", 2, "b")])])[0]])
    assert raw.startswith(b"\xef\xbb\xbf")
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    assert tuple(rows[0]) == D.CSV_COLUMNS
    assert rows[0]["category_name"] == "requirement" and rows[0]["flags"] == "mandatory"
    assert rows[0]["problems"] == "number 24 not in cited text"
    assert rows[1]["text"] == "Café — Zürich"
    assert rows[1]["page_labels"] == "1; 2" and rows[1]["citation_ids"] == "p1.1; p2.1"
    assert rows[1]["source_text"] == "a / b" and rows[1]["sections"] == "S1; S2"
    assert D.csv_name("rfp/1", "run_x") == "rfp_1_run_x_facts.csv"


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def test_find_runs_skips_non_fact_json(tmp_path):
    write(tmp_path / "a" / "facts.json", [fact("B", "x", [("p1.1", 1, "x")])])
    write(tmp_path / "a" / "report.json", {"run_id": "run_x", "pages": 7})
    write(tmp_path / "facts_run1.json", [fact("B", "y"), fact("R", "z")])
    write(tmp_path / "facts_run1.judge.json", {"pairs": []})
    write(tmp_path / "a" / "facts.judge.json", [{"gold": "x", "found": "y"}])
    write(tmp_path / "b" / "facts.json", [])  # an empty run still opens
    (tmp_path / "facts_bad.json").write_text("{not json")
    runs = D.find_runs(tmp_path)
    assert sorted(r.label for r in runs) == ["a/facts.json", "b/facts.json", "facts_run1.json"]
    assert {r.label: r.facts for r in runs}["facts_run1.json"] == 2
    assert D.find_runs(tmp_path / "missing") == []
    run = D.load_run(tmp_path / "a" / "facts.json")
    assert run.report == {"run_id": "run_x", "pages": 7} and run.pages == 7 and run.pdf is None
    assert D.report_path(tmp_path / "facts_run1.json").name == "report_run1.json"
    empty = D.load_run(tmp_path / "b" / "facts.json")
    assert empty.records == [] and empty.pages == 1


def test_code_differences():
    a = D.normalize([fact("C", "liability", [("p3.4", 3, "")]), fact("R", "support", [("p3.10", 3, "")]),
                     fact("D", "due", [("p1.2", 1, "")])])
    b = D.normalize([fact("X", "liability reject", [("p3.4", 3, "")]), fact("R", "support 2", [("p3.10", 3, "")]),
                     fact("C", "due too", [("p1.2", 1, "")]), fact("D", "due", [("p1.2", 1, "")])])
    assert D.code_differences(a, b) == [
        {"id": "p1.2", "codes_a": "D", "codes_b": "CD", "facts_a": "due", "facts_b": "due too / due"},
        {"id": "p3.4", "codes_a": "C", "codes_b": "X", "facts_a": "liability", "facts_b": "liability reject"},
    ]


def make_pdf(path, pages=2):
    doc = pymupdf.open()
    for i in range(pages):
        p = doc.new_page()
        p.insert_text((72, 100), f"Page {i + 1}. The vendor shall provide support for the system.", fontsize=11)
        p.insert_text((72, 130), "Proposals are due March 3, 2027 at 5:00 PM.", fontsize=11)
    doc.save(str(path))
    doc.close()
    return path


def test_render_page_png_and_pdf_untouched(tmp_path):
    pdf = make_pdf(tmp_path / "t.pdf")
    before = pdf.read_bytes()
    png = D.render_page(pdf, 2, [[70, 88, 400, 104], None])  # a citation with bbox null is skipped
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    plain = D.render_page(pdf, 2, [])
    assert png != plain  # the highlight is drawn
    assert D.render_page(before, 2, [[70, 88, 400, 104]]) == png  # bytes work like a path
    assert pdf.read_bytes() == before


def test_safe_name():
    assert D.safe_name("RFP 24/0031: ERP") == "RFP_24_0031__ERP"
    assert D.safe_name("..") == "_"


def _unit_client(label="D"):
    def handler(req):
        kind = req.task.split("\n", 1)[0]
        if kind in ("TASK CHECK", "TASK GROUP", "TASK BRIEF"):
            return "END|0\n"
        ids = [i.strip() for i in req.task.splitlines()[2].split(",")]
        return "\n".join(f"{i}|{label if kind == 'TASK LABEL' else '-'}" for i in ids) + "\nEND|1\n"

    return ScriptedClient(handler)


def test_run_extraction_stores_the_result_and_reuses_it(tmp_path):
    from fact_extractor import units

    pdf = make_pdf(tmp_path / "in.pdf").read_bytes()
    cfg = units.Config(backoff_base=0, warmup_timeout=1)
    runs = tmp_path / "runs"
    facts_path, report, stored = D.run_extraction(
        pdf, deal_id="d1", doc_id="rfp 1", model=None, runs_root=runs, client=_unit_client(), cfg=cfg,
    )
    assert not stored and facts_path.parent.parent == runs / "rfp_1"
    assert sorted(p.name for p in facts_path.parent.iterdir()) == [
        "facts.json", "labels.json", "meta.json", "report.json", "source.pdf"]
    assert (facts_path.parent / "source.pdf").read_bytes() == pdf
    assert not (runs / ".staging").exists()
    assert {r["category"] for r in json.loads(facts_path.read_text())} == {"D"}
    assert D.result_line(report).startswith(f"{report['facts']} facts from ")
    assert [r.path for r in D.find_runs(runs)] == [facts_path]
    assert D.stored_result(pdf, "rfp 1", runs).facts_path == facts_path
    # The same PDF again: the stored result, and no model call.
    idle = ScriptedClient(lambda req: AssertionError("no call expected"))
    again, _, stored = D.run_extraction(pdf, deal_id="d1", doc_id="rfp 1", model=None, runs_root=runs, client=idle, cfg=cfg)
    assert stored and again == facts_path and idle.requests == []
    # Asked to extract again: a second result beside the first.
    third, _, stored = D.run_extraction(
        pdf, deal_id="d1", doc_id="rfp 1", model=None, runs_root=runs, client=_unit_client("R"), cfg=cfg, refresh=True)
    assert not stored and third != facts_path and facts_path.exists()


def test_run_extraction_writes_nothing_on_error(tmp_path):
    client = ScriptedClient(lambda req: AssertionError("no call expected"))
    with pytest.raises(Exception):
        D.run_extraction(b"not a pdf", deal_id="d", doc_id="x", model=None, runs_root=tmp_path / "runs", client=client)
    assert not (tmp_path / "runs").exists()
    assert client.requests == []


def test_ui_command_without_streamlit(monkeypatch, capsys):
    import importlib.util

    from fact_extractor import cli

    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a: None if name == "streamlit" else real(name, *a))
    assert cli.main(["ui"]) == 1
    assert "uv sync --extra ui" in capsys.readouterr().err


def test_bid_and_after_award_views():
    def rec(text, *flags, cat="C"):
        return D.normalize([{"category": cat, "text": text, "citations": [], "flags": list(flags)}])[0]

    gate = rec("Hold an NC licence at submission", cat="G")
    cert = rec("Send the certificate of insurance after award", "post-award")
    limit = rec("Maintain general liability of $1,000,000 per occurrence", "post-award")
    indemnity = rec("Indemnify the City without limit", "risk", "post-award")
    recs = [gate, cert, limit, indemnity]
    assert D.filter_facts(recs, view="Bid") == [gate, limit, indemnity]  # amounts and risks stay in the bid view
    assert D.filter_facts(recs, view="After award") == [cert, limit, indemnity]
    assert D.filter_facts(recs, view="All") == recs
    s = D.summary(recs)
    assert s["counts"]["after award"] == 3
    assert [o["text"] for o in s["price_or_risk"]] == [limit["text"], indemnity["text"]]
    assert s["price_or_risk"][1]["flags"] == "risk"
    # A run made before the flag existed: the bid view hides nothing.
    assert D.filter_facts(RECORDS, view="Bid") == RECORDS and D.filter_facts(RECORDS, view="After award") == []


def test_style_fragments_escape_document_text():
    from fact_extractor.ui import style as S

    evil = "<script>alert(1)</script> **bold**"
    r = D.normalize([{"category": "C", "text": evil, "flags": ["risk"], "note": evil, "citations": [
        {"id": "p1.1", "page": 1, "page_label": "1", "section": evil, "text": evil, "bbox": None}]}])[0]
    for html in (S.fact_card(r), S.citations(r["citations"]), S.list_card(evil, "C", [{"text": evil, "page": "1"}]),
                 S.header(evil, evil, 1, 1, evil), S.stats([(evil, evil, evil, "")]), S.bars(evil, {evil: 1})):
        assert "<script>" not in html and "&lt;script&gt;" in html
    many = S.list_card("Dates", "D", [{"text": f"d{i}", "page": "1"} for i in range(12)])
    assert "Show all 12" in many and many.count("<li>") == 12


def test_run_list_carries_timings(tmp_path):
    run = tmp_path / "a"
    run.mkdir()
    (run / "facts.json").write_text(json.dumps([fact("D", "Due 2027-03-05", [("p1.1", 1, "Due March 5, 2027.")])]))
    (run / "report.json").write_text(json.dumps(
        {"seconds": {"extract": 20.5, "sweep_and_check": 16.25, "total": 36.98}, "output_tokens": 25418}))
    (tmp_path / "facts_old.json").write_text(json.dumps([fact("D", "x", [("p1.1", 1, "x")])]))  # no report
    refs = {r.label: r for r in D.find_runs(tmp_path)}
    assert D.took(refs["a/facts.json"].seconds) == "37 s" and D.took(refs["facts_old.json"].seconds) == ""
    assert D.took({"total": 125.4}) == "2 min 5 s"
    row = next(r for r in D.runs_table(list(refs.values())) if r["run"] == "a")
    assert (row["total s"], row["extract s"], row["sweep and check s"], row["output tokens"]) == (36.98, 20.5, 16.25, 25418)
    assert next(r for r in D.runs_table(list(refs.values())) if r["run"] == "facts_old.json")["total s"] is None


def test_items_collapse_groups_in_place():
    def rec(text, page, gid="", kind="", title=""):
        r = fact("R", text, [(f"p{page}.1", page, text)])
        return D.normalize([{**r, "group_id": gid, "group_kind": kind, "group_title": title}])[0]

    a = rec("Provide a bond", 1)
    b = rec("Scope includes module A", 2, "g1", "list", "Modules in scope")
    c = rec("Questions due 2027-03-01", 3, "g2", "same", "Questions due 2027-03-01")
    d = rec("Scope includes module B", 4, "g1", "list", "Modules in scope")
    e = rec("Questions due 2027-03-01", 5, "g2", "same", "Questions due 2027-03-01")
    got = D.items([a, b, c, d, e])
    assert [(i.kind, i.title, len(i.facts)) for i in got] == [
        ("fact", "Provide a bond", 1), ("list", "Modules in scope", 2), ("same", "Questions due 2027-03-01", 2)]
    assert got[1].pages() == "2; 4"
    # A point stated in two places opens with both places cited.
    assert [c["id"] for c in D.merged(got[2])["citations"]] == ["p3.1", "p5.1"]
    # With the other members filtered out, a grouped fact is shown as the plain fact it is.
    assert [(i.kind, len(i.facts)) for i in D.items([a, b, c])] == [("fact", 1), ("fact", 1), ("fact", 1)]
    # The Summary lists a list once, by its title and size, and a repeated point once.
    s = D.summary([a, b, c, d, e])
    assert s["facts"] == 5
    rows = [r["text"] for r in D.summary([{**x, "category": "D"} for x in (a, b, c, d, e)])["dates"]]
    assert rows == ["Provide a bond", "Modules in scope (2 items)", "Questions due 2027-03-01"]


def test_overview_sections():
    def rec(cat, text, page, fid, **kw):
        r = fact(cat, text, [(f"p{page}.1", page, text)])
        return D.normalize([{**r, "fact_id": fid, **kw}])[0]

    recs = [
        rec("B", "The buyer is the City of Springfield", 1, "b1"),
        rec("B", "There are 500 users", 2, "b2"),
        rec("G", "Hold an NC licence", 3, "g1"),
        rec("X", "Late proposals are not opened", 3, "x1"),
        rec("E", "Price: 30 points", 4, "e1", group_id="g", group_kind="list", group_title="Evaluation criteria"),
        rec("E", "Experience: 70 points", 4, "e2", group_id="g", group_kind="list", group_title="Evaluation criteria"),
        rec("D", "Proposals due: 2027-03-05 14:00 ET", 5, "d1"),
        rec("D", "Questions due: 2027-02-10", 5, "d2"),
        rec("D", "Award: 30 days after presentations", 6, "d3"),
        rec("C", "Pay the stated wage", 7, "c1", flags=["unclear"]),
        rec("S", "Email one PDF to the buyer", 7, "s1"),
        rec("Q", "Due 2027-03-03 vs 2027-03-05", 8, "q1"),
    ]
    brief = [
        {"row": "Buyer", "text": "City of Springfield", "fact_ids": ["b1"], "checked": True},
        {"row": "Scale", "text": "900 users", "fact_ids": ["b2"], "checked": False},  # 900 is not in the fact
        {"row": "Why", "text": "", "fact_ids": [], "checked": False},
    ]
    gates = [{"row": "Who may bid", "text": "Holders of an NC licence", "fact_ids": ["g1"], "checked": True}]
    o = D.overview(recs, {"buyer": brief, "gates": gates})
    assert o["summary"]["gates"] == [{"row": "Who may bid", "text": "Holders of an NC licence", "page": "3"}]
    assert o["summary"]["scoring"] == []  # no summary stored for it: the screen lists its facts
    assert o["buyer"] == [
        {"row": "Buyer", "text": "City of Springfield", "page": "1"},
        {"row": "Scale", "text": "There are 500 users", "page": "2"},  # the cited fact, not the unchecked wording
        {"row": "Why", "text": "", "page": ""},
    ]
    assert [e["text"] for e in o["gates"]] == ["Hold an NC licence"]
    assert [e["text"] for e in o["disqualifiers"]] == ["Late proposals are not opened"]
    assert o["scoring"] == [{"text": "Evaluation criteria", "page": "4", "children": [
        {"text": "Price: 30 points", "page": "4"}, {"text": "Experience: 70 points", "page": "4"}]}]
    assert [e["text"] for e in o["unclear"]] == ["Pay the stated wage"]
    assert [e["text"] for e in o["submission"]] == ["Email one PDF to the buyer"]
    assert o["contradictions"][0]["text"] == "Due 2027-03-03 vs 2027-03-05"
    cal = o["calendar"]
    assert [(d["date"], d["time"]) for d in cal["dated"]] == [("2027-02-10", ""), ("2027-03-05", "14:00")]  # time order
    assert cal["dated"][0]["label"] == "Wed 10 Feb 2027"
    assert [u["text"] for u in cal["undated"]] == ["Award: 30 days after presentations"]
    assert D.overview(recs)["buyer"] == [] and len(D.overview(recs)["buyer_facts"]) == 2
