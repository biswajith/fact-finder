"""The unit-label pipeline (units.py), stored results (results.py) and ID scoring (score.py)."""

import json

import pytest
from conftest import ScriptedClient, task_name

from fact_extractor import results, units
from fact_extractor.compare import Item
from fact_extractor.llm import CallFailed
from fact_extractor.score import score

FAST = units.Config(backoff_base=0, warmup_timeout=1)

LABELS = {
    "p1.1": "B", "p1.2": "S", "p1.3": "D", "p1.4": "D",
    "p2.1": "R", "p2.2": "R|risk", "p2.3": "R|post-award", "p2.t1r1": "=", "p2.t1r2": "R",
    "p3.1": "S", "p3.2": "X+D",
}
STATEMENTS = {
    "p1.3": "Proposals due: 2027-03-03 17:00 Eastern",
    "p2.1": "Support 900 concurrent users",  # 900 is not in the unit: the RFP's words are shown
    "p2.2": "Provide 24/7 support",
}


def ids_of(req) -> list[str]:
    return [i.strip() for i in req.task.splitlines()[2].split(",")]


def scripted(labels=LABELS, statements=STATEMENTS, check="Q|Due 2027-03-03 vs 2027-03-05|p1.3,p3.2|\nEND|1\n",
             groups="END|0\n", xref="END|0\n", brief="Buyer|The City of Springfield|1\nScale|900 users|1\nWhy|not stated|\nEND|7\n"):
    def handler(req):
        kind = task_name(req)
        if kind == "CHECK":
            return check
        if kind == "XREF":
            return xref
        if kind == "GROUP":
            return groups(req) if callable(groups) else groups
        if kind == "BRIEF":
            return brief
        ids = ids_of(req)
        if kind == "LABEL":
            per_call = labels(req) if callable(labels) else labels
            return "\n".join(f"{i}|{per_call.get(i, '-')}" for i in ids) + f"\nEND|{len(ids)}\n"
        return "\n".join(f"{i}|{statements.get(i, '-')}" for i in ids) + f"\nEND|{len(ids)}\n"

    return ScriptedClient(handler)


async def test_facts_are_units(doc):
    client = scripted()
    res = await units.extract(doc, client, deal_id="d", cfg=FAST, run_id="r1")
    by_unit = {f["citations"][0]["id"]: f for f in res.facts if f["category"] != "Q"}
    assert set(by_unit) == set(LABELS) - {"p2.t1r1"}  # every coded unit is one fact; the continuation is not

    due = by_unit["p1.3"]
    assert due["text"] == "Proposals due: 2027-03-03 17:00 Eastern" and due["text_from"] == "model"
    assert due["source_text"] == "Proposals are due March 3, 2027 at 5:00 PM Eastern."
    assert due["status"] == "conflict" and due["conflicts"]  # shares a unit with the Q fact
    # A statement with a number the unit lacks is dropped: the fact shows the RFP's words.
    users = by_unit["p2.1"]
    assert users["text"] == "The system shall support 500 concurrent users." and users["text_from"] == "rfp"
    # A continuation joins the coded unit before it: one fact, both units cited.
    assert [c["id"] for c in by_unit["p2.3"]["citations"]] == ["p2.3", "p2.t1r1"]
    # mandatory comes from the unit's wording, the other flags from the votes.
    assert by_unit["p2.2"]["flags"] == ["mandatory", "risk"] and by_unit["p2.3"]["flags"] == ["mandatory", "post-award"]
    assert by_unit["p1.1"]["flags"] == []
    assert by_unit["p3.2"]["category"] == "X" and by_unit["p3.2"]["also"] == "D"
    assert all(f["agreement"] == "3/3" for f in by_unit.values())

    qs = [f for f in res.facts if f["category"] == "Q"]
    assert len(qs) == 1 and [c["id"] for c in qs[0]["citations"]] == ["p1.3", "p3.2"]

    r = res.report
    assert r["pipeline"] == units.VERSION and r["facts_votes_split"] == 0 and r["units_continuing"] == 1
    # The cache hit rate counts only the calls that send the document, after the first one.
    doc_calls = [c for c in r["calls"] if c["kind"] not in ("group", "brief")][1:]
    assert {c["kind"] for c in r["calls"]} > {c["kind"] for c in doc_calls}  # GROUP or BRIEF calls ran too
    hit = sum(c["usage"]["cached_tokens"] for c in doc_calls) / sum(c["usage"]["input_tokens"] for c in doc_calls)
    assert r["cache_hit_calls_2_to_n"] == round(hit, 3)
    assert len(res.labels) == len(doc.anchors)
    # One round on one cached prefix: three label votes, one statement pass, one check.
    first = [q for q in client.requests if task_name(q) not in ("GROUP", "BRIEF")]
    assert {(q.system, q.document) for q in first} == {(units.SYSTEM, doc.tagged_text)}
    assert sorted(task_name(q) for q in first) == ["CHECK", "LABEL", "LABEL", "LABEL", "STATE", "XREF"]
    # Then the grouping round, about the facts and without the document: only R has 4 facts.
    second = [q for q in client.requests if task_name(q) == "GROUP"]
    assert [(q.system, q.document) for q in second] == [(units.GROUP_SYSTEM, "")]
    assert all(f["group_id"] == "" for f in res.facts)  # the model found no group
    # The buyer brief: always the seven rows. A row whose numbers are not in the facts it
    # cites is not "checked", and an empty row has no text.
    rows = {b["row"]: b for b in r["summaries"]["buyer"]}
    assert list(rows) == [name for name, _ in units.SECTION["buyer"].rows]
    assert rows["Buyer"]["text"] == "The City of Springfield" and rows["Buyer"]["checked"]
    assert rows["Buyer"]["fact_ids"] == [by_unit["p1.1"]["fact_id"]]
    assert rows["Scale"]["text"] == "900 users" and not rows["Scale"]["checked"]
    assert rows["Why"] == {"row": "Why", "text": "", "fact_ids": [], "checked": False}
    # One summary call per section that has facts (no E facts here, so none for scoring),
    # each about the facts only; a section with no facts still gets its rows, empty.
    asked = {(q.system, q.document) for q in client.requests if task_name(q) == "BRIEF"}
    assert asked == {(units.brief_system(units.SECTION[k]), "") for k in ("buyer", "submission", "gates", "questions")}
    assert set(r["summaries"]) == {"buyer", "submission", "gates", "scoring", "questions"}
    assert [x["row"] for x in r["summaries"]["scoring"]] == ["Method", "Criteria", "Price", "Stages", "Who decides"]
    assert all(x["text"] == "" for x in r["summaries"]["scoring"])


async def test_fact_ids_do_not_depend_on_code_or_wording(doc):
    a = await units.extract(doc, scripted(), deal_id="d", cfg=FAST)
    other = dict(LABELS, **{"p1.2": "R", "p3.1": "R"})
    b = await units.extract(doc, scripted(other, {}), deal_id="d", cfg=FAST)
    assert {f["fact_id"] for f in a.facts} == {f["fact_id"] for f in b.facts}
    d = results.diff(a.facts, b.facts)
    assert d["recoded"] == ["p1.2: S -> R", "p3.1: S -> R"] and d["added"] == d["removed"] == 0


async def test_majority_vote_and_split_marker(doc):
    calls = {"n": 0}

    def labels(req):
        calls["n"] += 1
        # Vote 1 says S for p1.2 and nothing for p2.1; votes 2 and 3 say R for both.
        return dict(LABELS, **{"p1.2": "S", "p2.1": "-"}) if calls["n"] == 1 else dict(LABELS, **{"p1.2": "R"})

    res = await units.extract(doc, scripted(labels), deal_id="d", cfg=FAST)
    by_unit = {f["citations"][0]["id"]: f for f in res.facts if f["category"] != "Q"}
    assert by_unit["p1.2"]["category"] == "R" and by_unit["p1.2"]["agreement"] == "2/3"
    assert sorted(by_unit["p1.2"]["votes"]) == ["R", "R", "S"]
    assert by_unit["p2.1"]["category"] == "R" and by_unit["p2.1"]["agreement"] == "2/3"
    assert res.report["facts_votes_split"] == 2


async def test_grouping_marks_facts_and_never_removes_one(doc):
    labels = dict(LABELS, **{"p1.1": "R", "p1.2": "R", "p3.1": "R"})
    statements = {
        "p1.1": "Provide a records system", "p1.2": "Send questions by email",
        "p2.1": "Support 500 concurrent users", "p2.2": "Provide 24/7 support",
        "p2.3": "Keep data for 7 years", "p2.t1r2": "Provide 24/7 support",
        "p3.1": "Keep proposals to 50 pages",
    }

    def groups(req):
        lines = {ln.split("|")[2]: ln.split("|")[0] for ln in req.task.splitlines() if ln[:1].isdigit()}
        n = lines.__getitem__
        return (
            f"SAME|{n('Provide 24/7 support')},{n('Provide a records system')}\n"  # only one line has that text twice
            f"LIST|Capacity and retention|{n('Support 500 concurrent users')},{n('Keep data for 7 years')}\n"
            f"SAME|{n('Send questions by email')},{n('Keep proposals to 50 pages')}\nEND|3\n"
        )

    res = await units.extract(doc, scripted(labels, statements, groups=groups), deal_id="d", cfg=FAST)
    by_text = {f["text"]: f for f in res.facts if f["category"] == "R"}
    assert len([f for f in res.facts if f["category"] == "R"]) == 7  # grouping removes nothing
    a, b = by_text["Support 500 concurrent users"], by_text["Keep data for 7 years"]
    assert a["group_id"] == b["group_id"] != "" and a["group_kind"] == "list" and a["group_title"] == "Capacity and retention"
    # "Same" with different numbers is not the same point: kept visible, as a list.
    q, pages = by_text["Send questions by email"], by_text["Keep proposals to 50 pages"]
    assert q["group_id"] == pages["group_id"] and q["group_kind"] == "list" and q["group_title"] == "Related statements"
    assert res.report["facts_in_groups"] >= 4 and res.report["seconds"]["group_and_summaries"] >= 0


def test_parse_brief_joins_items_cited_one_by_one():
    facts = [{"fact_id": f"f{n}", "text": t} for n, t in enumerate(["Appendix A is missing.", "Appendix B is missing.", "Dates are not set."], 1)]
    rows = ("Contradictions", "Unclear points")
    # the items' numbers separated by semicolons
    got = units.parse_brief("Contradictions|not stated|\nUnclear points|Can you send Appendix A and B?; When are the dates?|1,2;3\nEND|2", facts, rows)
    assert got[1] == {"row": "Unclear points", "text": "Can you send Appendix A and B?; When are the dates?",
                      "fact_ids": ["f1", "f2", "f3"], "checked": True}
    # the row repeated once per item
    again = units.parse_brief("Unclear points|Can you send Appendix A and B?|1,2\nUnclear points|When are the dates?|3\nEND|2", facts, rows)
    assert again[1] == got[1] and again[0] == {"row": "Contradictions", "text": "", "fact_ids": [], "checked": False}


def test_parse_brief_drops_items_that_only_say_not_stated():
    facts = [{"fact_id": "f1", "text": "Liability insurance of at least $1,000,000 per occurrence."}]
    got = units.parse_brief("Insurance and bonds|Liability insurance at least $1,000,000 per occurrence; bonds not stated.|1\n"
                            "Termination|termination consequences not stated|1\nEND|2", facts, ("Insurance and bonds", "Termination"))
    assert got[0] == {"row": "Insurance and bonds", "text": "Liability insurance at least $1,000,000 per occurrence",
                      "fact_ids": ["f1"], "checked": True}
    assert got[1] == {"row": "Termination", "text": "", "fact_ids": [], "checked": False}


def test_parse_groups_keeps_a_line_in_one_group():
    got = units.parse_groups("SAME|1,2\nLIST|Modules in scope|3, 4,5,9\nLIST||6,7\nSAME|2,8\nnoise\nSAME|6,7\nEND|4", 8)
    assert got == [("same", "", [1, 2]), ("list", "Modules in scope", [3, 4, 5]), ("same", "", [6, 7])]


def test_vote_without_majority_keeps_the_unit():
    passes = [{"u": (("R",), ())}, {"u": (("-",), ())}, {"u": (("S",), ())}]
    v = units.vote(passes, ["u", "gone"])
    assert v["u"].label == "S" and not v["u"].agreed  # S comes before R; a coded vote beats "nothing"
    assert v["gone"].label == units.NO_ANSWER and v["gone"].votes == ["?", "?", "?"]


def test_parse_labels_and_statements():
    ids = ["p1.1", "p1.2", "p1.3", "p1.4"]
    got = units.parse_labels("[p1.1]|x+d|Risk, mandatory\np1.2|=|risk\np1.3|Z|\np9.9|R|\np1.4 | - |\nEND|4", ids)
    assert got == {"p1.1": (("X", "D"), ("risk",)), "p1.2": (("=",), ()), "p1.4": (("-",), ())}
    assert units.parse_statements("p1.1|Provide a bond|\np1.2|-\np1.3|\nnoise\nEND|3", ids) == {"p1.1": "Provide a bond"}
    leaked = units.parse_statements("p1.1|X: The City may reject it\np1.2|R, post-award: Verify compliance\np1.3|RFP issued: 2024-05-10", ids)
    assert leaked == {"p1.1": "The City may reject it", "p1.2": "Verify compliance", "p1.3": "RFP issued: 2024-05-10"}


def test_modal_flags_come_from_the_wording():
    assert units.modal_flags("R", "The vendor shall provide support.") == ["mandatory"]
    assert units.modal_flags("R", "Vendors should describe their approach.") == ["desirable"]
    assert units.modal_flags("R", "Vendors should and must comply.") == ["mandatory"]
    assert units.modal_flags("R", "Describe the approach.") == []
    assert units.modal_flags("B", "The City must replace its system.") == []  # not about the bidder


async def test_a_failed_call_costs_one_vote_not_the_run(doc):
    state = {"n": 0}

    def labels(req):
        state["n"] += 1
        if state["n"] <= 2:  # the first label call fails, and so does its one retry
            raise CallFailed("boom")
        return LABELS

    def handler(req):
        kind = task_name(req)
        if kind == "LABEL":
            ids = ids_of(req)
            try:
                per = labels(req)
            except CallFailed as e:
                return e
            return "\n".join(f"{i}|{per.get(i, '-')}" for i in ids) + "\nEND|1\n"
        return "END|0\n"

    res = await units.extract(doc, ScriptedClient(handler), deal_id="d", cfg=FAST)
    assert len(res.report["failed_calls"]) == 1
    facts = [f for f in res.facts if f["category"] != "Q"]
    assert len(facts) == len(LABELS) - 1 and all(f["agreement"] == "2/3" for f in facts)


async def test_result_is_stored_and_found_by_pdf_content(doc, tmp_path):
    pdf = tmp_path / "rfp.pdf"
    pdf.write_bytes(b"%PDF-1.4 same bytes")
    store = results.ResultStore(tmp_path / "runs")
    sha = results.pdf_hash(pdf)
    assert store.find(sha, units.VERSION, doc.doc_id) is None
    res = await units.extract(doc, scripted(), deal_id="d", cfg=FAST, run_id="run_a")
    saved = store.save(pdf, sha, units.VERSION, res, res.labels)
    assert sorted(p.name for p in saved.folder.iterdir()) == ["facts.json", "labels.json", "meta.json", "report.json", "source.pdf"]
    found = store.find(sha, units.VERSION, doc.doc_id)
    assert found.folder == saved.folder and found.facts() == json.loads(json.dumps(res.facts))
    # Another PDF, another pipeline version or another doc ID is another result.
    assert store.find(results.pdf_hash(b"other"), units.VERSION, doc.doc_id) is None
    assert store.find(sha, "units-0", doc.doc_id) is None and store.find(sha, units.VERSION, "x") is None
    assert store.latest(sha, doc.doc_id).folder == saved.folder


async def test_find_is_per_playbook_and_a_legacy_meta_counts_as_rfp(doc, tmp_path):
    store = results.ResultStore(tmp_path / "runs")
    sha = results.pdf_hash(b"pdf bytes")
    res = await units.extract(doc, scripted(), deal_id="d", cfg=FAST, run_id="run_a")
    saved = store.save(b"pdf bytes", sha, units.VERSION, res, res.labels, source_name="Bid.PDF", units=doc)
    assert saved.meta["playbook"] == "rfp@1" and saved.meta["source_file"] == "source.pdf"
    assert saved.meta["source_name"] == "Bid.PDF"
    assert store.find(sha, units.VERSION, doc.doc_id, "rfp@1").folder == saved.folder
    assert store.find(sha, units.VERSION, doc.doc_id, "deal-notes@1") is None
    # a result stored before playbooks existed has no playbook in its meta
    meta = json.loads((saved.folder / "meta.json").read_text())
    for key in ("playbook", "source_name", "source_file"):
        del meta[key]
    (saved.folder / "meta.json").write_text(json.dumps(meta))
    assert store.find(sha, units.VERSION, doc.doc_id).folder == saved.folder
    assert store.find(sha, units.VERSION, doc.doc_id, "change-addendum@1") is None


async def test_a_non_pdf_source_is_stored_under_its_own_extension_and_units_round_trip(doc, tmp_path):
    store = results.ResultStore(tmp_path / "runs")
    res = await units.extract(doc, scripted(), deal_id="d", cfg=FAST, run_id="run_a")
    saved = store.save(b"{}", "abc", units.VERSION, res, playbook="call-transcript@1", source_name="call.gong.json", units=doc)
    assert saved.meta["source_file"] == "source.json" and (saved.folder / "source.json").read_bytes() == b"{}"
    assert not (saved.folder / "source.pdf").exists()
    back = results.load_document(saved.folder, doc.doc_id)
    assert back.tagged_text == doc.tagged_text and back.anchors == doc.anchors and back.page_count == doc.page_count


async def test_units_of_two_documents_with_the_same_ids_do_not_share_a_conflict(doc):
    res = await units.extract(doc, scripted(), deal_id="d", cfg=FAST)
    plain = [r for r in res.facts if r["category"] != "Q"]
    q = {"category": "Q", "fact_id": "q1", "doc_id": "other", "citations": [{"doc_id": "other", "id": plain[0]["citations"][0]["id"]}]}
    records = [dict(r, conflicts=[]) for r in plain] + [q]
    for r in records:
        r["status"] = "valid"
    units._mark_conflicts(records)
    assert all(r["conflicts"] == [] for r in records if r["category"] != "Q")
    q["citations"][0]["doc_id"] = doc.doc_id
    units._mark_conflicts(records)
    assert records[0]["conflicts"] == ["q1"] and records[0]["status"] == "conflict"


def test_cli_shows_the_stored_result_without_a_model_call(tmp_path, monkeypatch, capsys):
    import fact_extractor.llm as llm
    from fact_extractor import cli
    from test_web_runs import make_pdf

    pdf = make_pdf(tmp_path / "rfp.pdf")
    made = []

    class Fake(ScriptedClient):
        def __init__(self, model=None):
            super().__init__(scripted({"p1.1": "R"}, {}, "END|0\n").handler)
            made.append(self)

    monkeypatch.setattr(llm, "OpenAIClient", Fake)
    monkeypatch.chdir(tmp_path)
    args = ["extract", str(pdf), "--deal-id", "d", "--out", str(tmp_path / "facts.json")]
    assert cli.main(args) == 0
    first = json.loads((tmp_path / "facts.json").read_text())
    assert len(made) == 1 and made[0].requests and "stored in" in capsys.readouterr().err
    assert cli.main(args) == 0  # same PDF again: the stored result, no client made
    assert len(made) == 1 and "No model call" in capsys.readouterr().err
    assert json.loads((tmp_path / "facts.json").read_text()) == first
    assert cli.main(args + ["--refresh"]) == 0
    assert len(made) == 2 and "facts the same" in capsys.readouterr().err


def test_score_by_source_id():
    def rec(cat, *ids, also=None):
        return {"category": cat, "also": also, "citations": [{"id": i} for i in ids]}

    gold = [
        Item("R", "a", ["p1.1"], []), Item("S", "b", ["p1.2"], [], alt=["R"]), Item("D", "c", ["p1.3"], []),
        Item("G", "d", ["p1.4", "p1.5"], []), Item("Q", "e", ["p2.1", "p2.2"], []),
    ]
    records = [rec("R", "p1.1"), rec("R", "p1.2"), rec("X", "p1.3", also="D"), rec("C", "p1.5"), rec("Q", "p2.2", "p9.9")]
    s = score(gold, records)
    assert s["gold"] == 5 and s["recall"] == 0.8 and s["recall_same_code"] == 0.8
    assert [m["id"] for m in s["missed"]] == ["p1.4"]  # only the main ID counts
    assert s["by_category"]["S"]["same_code"] == 1 and s["by_category"]["D"]["same_code"] == 1
    assert score(gold, []) ["recall"] == 0.0


def _label_handler(answers):
    """LABEL answers taken in turn from `answers` (functions of the ids); other tasks complete."""
    it = iter(answers)

    def handler(req):
        kind = task_name(req)
        if kind in ("CHECK", "GROUP", "BRIEF"):
            return "END|0\n"
        ids = ids_of(req)
        if kind == "STATE":
            return "\n".join(f"{i}|-" for i in ids) + f"\nEND|{len(ids)}\n"
        return next(it)(ids)

    return handler


def _full(ids):
    return "\n".join(f"{i}|{LABELS.get(i, '-')}" for i in ids) + f"\nEND|{len(ids)}\n"


def _short(n):
    """The first n units, then the model's own notes instead of labels, and no END line."""
    return lambda ids: "\n".join(f"{i}|{LABELS.get(i, '-')}" for i in ids[:n]) + "\nNo brackets. flags. p1.3 dates issue and due; D\n"


async def test_an_incomplete_answer_is_asked_again(doc):
    cfg = units.Config(backoff_base=0, warmup_timeout=1, votes=1, statements=False, check=False, xref=False, grouping=False, brief=False)
    client = ScriptedClient(_label_handler([_short(3), _full]))
    res = await units.extract(doc, client, deal_id="d", cfg=cfg)
    (call,) = res.report["calls"]
    assert call["status"] == "ok" and call["retries"] == 1 and "answered 3 of 15 units, no END line" in call["log"][0]  # the log names both faults
    assert res.report["incomplete_calls"] == [] and res.report["retried_calls"] == ["LABEL1#1"]
    assert res.report["units_unanswered_votes"] == 0
    assert len(res.facts) == len(LABELS) - 1  # with one vote, the short answer alone would have lost most units


async def test_still_incomplete_keeps_the_fuller_answer_and_says_so(doc):
    cfg = units.Config(backoff_base=0, warmup_timeout=1, votes=1, statements=False, check=False, xref=False, grouping=False, brief=False)
    res = await units.extract(doc, ScriptedClient(_label_handler([_short(9), _short(4)])), deal_id="d", cfg=cfg)
    (call,) = res.report["calls"]
    assert call["status"] == "incomplete" and "covering 9 of 15 units" in call["log"][-1]
    assert res.report["incomplete_calls"] == ["LABEL1#1"] and res.report["failed_calls"] == []
    assert res.report["units_unanswered_votes"] == 6
    assert {l["id"] for l in res.labels if l["votes"] == ["?"]} == set(list(doc.anchors)[9:])
    # An error on the retry does not throw away the lines the first answer did give.
    res = await units.extract(
        doc, ScriptedClient(_label_handler([_short(9), lambda ids: CallFailed("boom"), lambda ids: CallFailed("boom")])),
        deal_id="d", cfg=cfg)
    assert res.report["calls"][0]["status"] == "incomplete" and res.report["units_unanswered_votes"] == 6


async def test_all_units_answered_without_end_is_accepted_and_logged(doc):
    cfg = units.Config(backoff_base=0, warmup_timeout=1, votes=1, statements=False, check=False, xref=False, grouping=False, brief=False)
    no_end = lambda ids: "\n".join(f"{i}|{LABELS.get(i, '-')}" for i in ids) + "\n"  # noqa: E731
    res = await units.extract(doc, ScriptedClient(_label_handler([no_end])), deal_id="d", cfg=cfg)
    (call,) = res.report["calls"]
    assert call["status"] == "ok" and call["retries"] == 0 and call["log"] == ["every unit answered, but no END line"]
    assert units.stated_ids("p1.1|-\n[p1.2]|Provide a bond\np1.3|\nnotes\nEND|2", ["p1.1", "p1.2", "p1.3"]) == {"p1.1", "p1.2"}
    assert units.has_end("x\n end|3 \n") and not units.has_end("p1.1|R\nTHE END")


