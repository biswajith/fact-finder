"""The typed library surface (api.py): units in, tagged document and typed facts out."""

import dataclasses
import subprocess
import sys

import pytest
from conftest import ScriptedClient, task_name

from fact_extractor import units
from fact_extractor.api import LabelledFact, SourceUnit, document_from_units, label_units
from fact_extractor.validate import _ID


def U(key, text, kind="sentence", page=1, label="1", section=""):
    return SourceUnit(key, text, kind, page, label, section)


UNITS = [
    U("h-a", "1. Introduction", "heading", 1, "i", "1. Introduction"),
    U("s-1", "The City seeks proposals. Questions go to jane@x.gov.", "sentence", 1, "i", "1. Introduction"),
    U("s-2", "Proposals are due March 3, 2027.", "sentence", 1, "i", "1. Introduction"),
    U("h-b", "2. Requirements", "heading", 2, "1", "2. Requirements"),
    U("l-1", "The vendor must provide 24/7 support.", "list_item", 2, "1", "2. Requirements"),
    U("t-1", "Item: Uptime | Requirement: 99.9%", "table_row", 2, "1", "2. Requirements"),
    U("t-2", "Item: Hours | Requirement: 24/7", "table_row", 2, "1", "2. Requirements"),
    U("e", "   ", "sentence", 2, "1", "2. Requirements"),
    U("s-3", "Proposals are due March 5, 2027.", "sentence", 3, "2", ""),
]


def test_one_anchor_per_unit_with_valid_ids_and_round_trip():
    doc, id_map = document_from_units("d1", UNITS)
    assert len(doc.anchors) == 8 and len(id_map) == 8  # the empty unit is skipped
    assert all(_ID.match(i) for i in doc.anchors) and list(doc.anchors) == list(id_map)
    assert list(doc.anchors) == ["p1.h1", "p1.1", "p1.2", "p2.h1", "p2.1", "p2.t1r1", "p2.t1r2", "p3.1"]
    assert [id_map[i] for i in doc.anchors] == ["h-a", "s-1", "s-2", "h-b", "l-1", "t-1", "t-2", "s-3"]
    # A caller's unit is not split into sentences.
    assert doc.anchors["p1.1"].text == "The City seeks proposals. Questions go to jane@x.gov."
    a = doc.anchors["p2.t1r1"]
    assert (a.kind, a.page_label, a.section, a.doc_id) == ("table_row", "1", "2. Requirements", "d1")
    assert doc.anchors["p2.1"].kind == "list_item" and doc.anchors["p3.1"].section == ""
    assert doc.page_count == 3 and doc.tagged_text.count("\n") == 8
    assert "[p2.t1r1] Item: Uptime ; Requirement: 99.9%" in doc.tagged_text  # as tag_pages shows a row
    assert "[p1.1] The City seeks proposals. Questions go to jane@x.gov." in doc.tagged_text


def test_tagged_text_escapes_brackets_and_collapses_whitespace():
    doc, _ = document_from_units("d", [U("a", "See [p1.2]\nfor   details")])
    assert doc.tagged_text == "[p1.1] See (p1.2) for details\n"


def test_tables_are_numbered_per_run_and_headings_cut_them():
    us = [
        U("r1", "A: 1", "table_row"), U("r2", "A: 2", "table_row"),
        U("x", "Between.", "sentence"),
        U("r3", "A: 3", "table_row"), U("h", "Next", "heading"), U("r4", "A: 4", "table_row"),
    ]
    doc, m = document_from_units("d", us)
    assert list(doc.anchors) == ["p1.t1r1", "p1.t1r2", "p1.1", "p1.t2r1", "p1.h1", "p1.t3r1"]
    assert doc.anchors["p1.h1"].section == "Next"  # an empty section on a heading is its own text
    assert m["p1.t3r1"] == "r4"


def test_documents_without_pages_are_cut_into_pages_and_pages_may_repeat():
    n = 100
    doc, m = document_from_units("d", [U(f"k{i}", f"Unit number {i}.") for i in range(n)])
    assert len(doc.anchors) == n and doc.page_count == 3 and all(_ID.match(i) for i in doc.anchors)
    sizes = [len(doc.ids_on_page(p)) for p in (1, 2, 3)]
    assert sizes == [40, 40, 20]
    assert [m[i] for i in doc.anchors] == [f"k{i}" for i in range(n)]
    # The same caller page again, after another: a new page for the model, still in order.
    doc2, m2 = document_from_units("d", [U("a", "A.", page=1), U("b", "B.", page=2), U("c", "C.", page=1)])
    assert list(doc2.anchors) == ["p1.1", "p2.1", "p3.1"] and m2["p3.1"] == "c"


def test_empty_and_duplicates():
    doc, m = document_from_units("d", [U("a", "  ")])
    assert doc.anchors == {} and m == {} and doc.tagged_text == ""
    with pytest.raises(ValueError, match="duplicate"):
        document_from_units("d", [U("a", "One."), U("a", "Two.")])


def test_chunks_follow_the_virtual_pages():
    doc, _ = document_from_units("d", [U(f"k{i}", f"Unit {i}.") for i in range(130)])
    assert [len(c) for c in units.chunks(doc, 60)] == [80, 50]  # no chunk of the whole document


# --- label_units -------------------------------------------------------------------------

LABELS = {"p1.1": "B", "p1.2": "D", "p2.1": "R", "p2.t1r1": "=", "p2.t1r2": "R|risk", "p3.1": "D"}


def fake(labels=LABELS, check="Q|Due March 3 vs March 5|p1.2,p3.1|\nEND|1\n"):
    def handler(req):
        kind = task_name(req)
        if kind == "CHECK":
            return check
        ids = [i.strip() for i in req.task.splitlines()[2].split(",")]
        if kind == "LABEL":
            return "\n".join(f"{i}|{labels.get(i, '-')}" for i in ids) + f"\nEND|{len(ids)}\n"
        return "\n".join(f"{i}|-" for i in ids) + f"\nEND|{len(ids)}\n"

    return ScriptedClient(handler)


async def test_label_units_end_to_end():
    client = fake()
    res = await label_units("d1", UNITS, client, votes=2)
    facts = res.facts
    by_first = {f.unit_keys[0]: f for f in facts if f.category != "Q"}
    assert set(by_first) == {"s-1", "s-2", "l-1", "t-2", "s-3"}
    assert all(isinstance(f, LabelledFact) and isinstance(f.unit_keys, tuple) for f in facts)
    assert by_first["l-1"].category == "R" and by_first["l-1"].unit_keys == ("l-1", "t-1")  # continuation joins
    assert by_first["l-1"].flags == ("mandatory",)  # from the unit's wording
    assert by_first["t-2"].flags == ("risk",) and by_first["s-1"].flags == ()
    assert by_first["s-1"].text == "The City seeks proposals. Questions go to jane@x.gov."
    # The contradiction: a Q fact, and the facts that share its units point at its index.
    qi = [n for n, f in enumerate(facts) if f.category == "Q"]
    assert len(qi) == 1 and facts[qi[0]].unit_keys == ("s-2", "s-3")
    for k in ("s-2", "s-3"):
        assert by_first[k].status == "conflict" and by_first[k].conflicts_with == (qi[0],)
    assert by_first["s-1"].status == "valid" and by_first["s-1"].conflicts_with == ()
    assert facts[qi[0]].conflicts_with == ()
    # Model-facing text never carries the caller's keys.
    assert not any("s-1" in r.document or "t-2" in r.document for r in client.requests)
    assert res.failed_calls == () and res.calls == len(client.requests) and res.calls >= 4
    assert res.input_tokens > 0 and res.output_tokens > 0
    assert dataclasses.is_dataclass(res) and res.__dataclass_params__.frozen  # type: ignore[attr-defined]


async def test_no_units_no_calls():
    client = fake()
    res = await label_units("d", [U("a", " ")], client)
    assert res.facts == () and res.calls == 0 and client.requests == []


async def test_failed_calls_are_reported_not_raised():
    from fact_extractor.llm import CallFailed

    def handler(req):
        return CallFailed("down")

    client = ScriptedClient(handler)
    res = await label_units("d", UNITS, client, votes=1)
    assert res.facts == () and res.failed_calls and res.calls == len(res.failed_calls)


async def test_unknown_ids_are_dropped_and_leave_needs_review(monkeypatch):
    from fact_extractor import api

    real = units.extract

    async def tampered(doc, client, **kw):
        run = await real(doc, client, **kw)
        run.facts[0]["citations"] = [{"id": "p9.9"}]  # not a unit of the caller's
        run.facts[1]["citations"][0]["id"] = "p9.9"  # one of two cited units unknown
        run.facts[1]["citations"].append(dict(run.facts[0]["citations"][0], id="p1.1"))
        return run

    monkeypatch.setattr(api._units, "extract", tampered)
    res = await label_units("d1", UNITS, fake(), votes=1)
    a, b = res.facts[0], res.facts[1]
    assert a.unit_keys == () and a.status == "needs_review" and "cited an unknown unit" in a.problems
    assert b.unit_keys == ("s-1",) and "cited an unknown unit" in b.problems and b.status == "conflict"


def test_importing_the_api_loads_no_pdf_or_model_library():
    code = (
        "import sys, fact_extractor.api\n"
        "bad = [m for m in ('pymupdf', 'fitz', 'openai') if m in sys.modules]\n"
        "assert not bad, bad\n"
        "import fact_extractor\n"
        "bad = [m for m in ('pymupdf', 'fitz', 'openai') if m in sys.modules]\n"
        "assert not bad, bad\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
