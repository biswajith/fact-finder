"""GROUP across a bid and the pair check (bidgroup.py, bid.settle). No model call is ever made."""

import ast
import json
from pathlib import Path

from conftest import ScriptedClient, task_name

from fact_extractor import bid as B
from fact_extractor import bidgroup as G
from fact_extractor import units
from fact_extractor.ladder import conflict_id
from fact_extractor.llm import CallFailed
from fact_extractor.web import runs

FAST = units.Config(backoff_base=0, warmup_timeout=1)


def fact(doc_no, doc_id, unit, text, cat="D", level=1, flags=(), replaced_by=""):
    return {
        "fact_id": f"f_{doc_id}_{unit}", "doc_id": doc_id, "doc_no": doc_no, "category": cat, "text": text, "source_text": text,
        "level": level, "flags": list(flags), "replaced_by": replaced_by, "stale": "", "relations": [],
        "group_id": "", "group_kind": "", "group_title": "",
        "citations": [{"id": unit, "page": 1, "page_label": "1", "doc_id": doc_id, "doc_no": doc_no}],
    }


class FakeChecker:
    """Stands in for ConsistencyChecker: the probability is the first of `by_text` whose key is in the
    existing fact's text (0.05 otherwise); it records every request."""

    def __init__(self, by_text=None, fail=None):
        self.by_text, self.fail, self.calls = by_text or {}, fail, []

    async def _ask(self, new_text, related, instructions=None):
        self.calls.append((new_text, [f["fact_id"] for f in related], instructions))
        if self.fail:
            raise self.fail
        return {f["fact_id"]: next((p for k, p in self.by_text.items() if k in f["text"]), 0.05) for f in related}, None


# --- GROUP's task -----------------------------------------------------------------------------


def test_group_task_is_unchanged_without_document_labels():
    facts = [fact(1, "A", "p1.1", "A|b"), fact(1, "A", "p1.2", "c")]
    facts[1]["citations"] = []
    assert units.group_task("D", facts) == "TASK GROUP\nCategory: D = dates\n\n1|1|A/b\n2||c"  # captured before WP5
    assert units.group_task("D", facts, {facts[0]["fact_id"]: "d2", facts[1]["fact_id"]: "d3"}) == (
        "TASK GROUP\nCategory: D = dates\n\n1|d2 p.1|A/b\n2|d3|c"
    )


def test_bidgroup_does_not_import_the_web_at_module_level():
    tree = ast.parse(Path(G.__file__).read_text(encoding="utf-8"))
    names = [n.module or "" for n in tree.body if isinstance(n, ast.ImportFrom)] + [a.name for n in tree.body if isinstance(n, ast.Import) for a in n.names]
    assert not any("web" in n.split(".") for n in names)


# --- GROUP over the bid --------------------------------------------------------------------------

FONT = "Font no smaller than 11 point"


def style_facts():
    """The RFP's page limit and font rule are replaced by Addendum 1, which states the font rule again."""
    return [
        fact(1, "RFP", "p3.1", "Page limit: 30 pages", "S", flags=["replaced"], replaced_by="f_ADD1_p2.1"),
        fact(1, "RFP", "p3.2", FONT, "S", flags=["replaced"], replaced_by="f_ADD1_p2.2"),
        fact(1, "RFP", "p3.3", "Bind the copies with a staple", "S"),
        fact(1, "RFP", "p3.4", "Number every page", "S"),
        fact(2, "ADD1", "p2.1", "Page limit: 40 pages, excluding resumes", "S"),
        fact(2, "ADD1", "p2.2", FONT, "S"),
    ]


def group_handler(req):
    lines = req.task.split("\n\n", 1)[1].splitlines()
    same = [ln.split("|")[0] for ln in lines if FONT in ln]
    return f"SAME|{','.join(same)}\nEND|1" if len(same) == 2 else "END|0"


async def test_a_restated_rule_is_one_same_group_shown_under_the_addendums_fact():
    facts = style_facts()
    client = ScriptedClient(group_handler)
    report = await G.group_bid(facts, "ulster", client, FAST)
    assert [task_name(r) for r in client.requests] == ["GROUP"]
    assert "|d1 p.1|" in client.requests[0].task and "|d2 p.1|" in client.requests[0].task  # each line names its document
    assert report["asked"] == ["S"] and report["calls"][0]["name"] == "GROUP.S"
    [g] = report["categories"]["S"]["groups"]
    assert (g["kind"], g["fact_ids"]) == ("same", ["f_RFP_p3.2", "f_ADD1_p2.2"])
    G.apply_stored_groups(facts, report, "ulster")
    grouped = [f for f in facts if f["group_id"]]
    assert {f["group_kind"] for f in grouped} == {"same"} and len({f["group_id"] for f in grouped}) == 1
    [item] = [it for it in runs.items(facts) if it.kind == "same"]
    assert item.first["fact_id"] == "f_ADD1_p2.2" and [f["doc_no"] for f in item.facts] == [2, 1]
    assert "replaced" in item.facts[1]["flags"] and "replaced" not in item.first["flags"]


def test_a_group_whose_members_are_all_replaced_shows_as_plain_facts():
    a = fact(1, "RFP", "p1.1", "Rule", flags=["replaced"])
    b = fact(2, "ADD1", "p1.1", "Rule", flags=["replaced"])
    a.update(group_id="g_1", group_kind="same"), b.update(group_id="g_1", group_kind="same")
    assert [(it.kind, len(it.facts)) for it in runs.items([a, b])] == [("fact", 1), ("fact", 1)]


def test_items_keep_the_order_of_records_without_a_level():
    a, b, c = (dict(fact(0, "R", f"p1.{i}", t), level=0, doc_no=0) for i, t in enumerate(["x", "y", "z"], start=1))
    for f in (a, b, c):
        f["flags"] = ["replaced"] if f is b else []
        f.update(group_id="g_1", group_kind="list", group_title="T")
        del f["level"]
    [item] = runs.items([a, b, c])
    assert [f["text"] for f in item.facts] == ["x", "y", "z"]


async def test_a_category_is_not_asked_again_until_its_facts_change():
    facts = style_facts()
    first = await G.group_bid(facts, "ulster", ScriptedClient(group_handler), FAST)
    again = ScriptedClient(group_handler)
    second = await G.group_bid(facts, "ulster", again, FAST, first)
    assert again.requests == [] and second["categories"] == first["categories"] and second["asked"] == []
    more = [*facts, fact(2, "ADD1", "p2.3", "Print on both sides", "S")]
    third = await G.group_bid(more, "ulster", again, FAST, first)
    assert len(again.requests) == 1 and third["asked"] == ["S"]
    assert third["categories"]["S"]["fact_ids"] == sorted(f["fact_id"] for f in more)


async def test_a_failed_call_stores_nothing_and_is_asked_again():
    facts = style_facts()
    failing = ScriptedClient(lambda r: CallFailed("down"))
    report = await G.group_bid(facts, "ulster", failing, FAST)
    assert report["categories"] == {} and report["asked"] == []
    retry = ScriptedClient(group_handler)
    assert (await G.group_bid(facts, "ulster", retry, FAST, report))["asked"] == ["S"]


async def test_a_category_needs_four_current_facts_from_two_documents():
    client = ScriptedClient(group_handler)
    one_doc = [fact(1, "RFP", f"p1.{i}", f"Rule {i}", "S") for i in range(5)]
    three = [fact(1, "RFP", "p1.1", "a", "S"), fact(1, "RFP", "p1.2", "b", "S"), fact(1, "RFP", "p1.3", "c", "S"), fact(2, "ADD1", "p1.1", "d", "S")]
    three[0]["flags"] = ["replaced"]
    assert (await G.group_bid(one_doc, "b", client, FAST))["categories"] == {}
    assert (await G.group_bid(three, "b", client, FAST))["categories"] == {}
    assert client.requests == []


async def test_a_same_group_whose_values_differ_is_related_statements_and_lists_a_pair():
    facts = [
        fact(1, "RFP", "p1.1", "Proposals are due June 10, 2:00 pm.", "D"), fact(1, "RFP", "p1.2", "Questions are due May 20.", "D"),
        fact(2, "ADD1", "p1.1", "Proposals are due June 24, 2:00 pm.", "D"), fact(2, "ADD1", "p1.2", "A site visit is held.", "D"),
    ]
    client = ScriptedClient(lambda r: "SAME|1,3\nEND|1")
    report = await G.group_bid(facts, "ulster", client, FAST)
    G.apply_stored_groups(facts, report, "ulster")
    assert {(f["group_kind"], f["group_title"]) for f in facts if f["group_id"]} == {("list", "Related statements")}
    [p] = G.pairs(facts)
    assert (p["reason"], p["old"], p["new"]) == ("related", "f_RFP_p1.1", "f_ADD1_p1.1") and p["id"].startswith("p_")


def test_group_ids_differ_between_two_bids_with_the_same_facts():
    facts = style_facts()
    report = {"categories": {"S": {"groups": [{"kind": "same", "title": "", "fact_ids": ["f_RFP_p3.2", "f_ADD1_p2.2"]}]}}}
    ids = []
    for bid_id in ("ulster", "dutchess"):
        G.apply_stored_groups(facts, report, bid_id)
        ids.append({f["group_id"] for f in facts if f["group_id"]})
    assert len(ids[0]) == len(ids[1]) == 1 and ids[0] != ids[1]


# --- the pairs and the pair check --------------------------------------------------------------------


def due_date_facts():
    """Addendum 2 moves the due date from June 10 to June 24."""
    return [
        fact(1, "RFP", "p1.1", "Proposals due: June 10, 2:00 pm", flags=["replaced"], replaced_by="f_ADD2_p1.4"),
        fact(1, "RFP", "p1.2", "Proposals received after June 10 will not be opened", "X"),
        fact(1, "RFP", "p1.3", "Deliver one signed original by June 10", "S"),
        fact(1, "RFP", "p1.4", "Questions are due ten days before the proposal due date"),
        fact(1, "RFP", "p1.5", "Optional site visit: June 10, 10:00 am"),
        fact(1, "RFP", "p1.6", "Insurance of 1 million is required", "R"),
        fact(2, "ADD2", "p1.4", "Proposals due: June 24, 2:00 pm"),
    ]


def test_pairs_list_the_facts_that_hold_the_old_value_and_the_ones_that_may_depend_on_it():
    facts = due_date_facts()
    got = G.pairs(facts)
    assert {(p["reason"], p["old"]) for p in got} == {
        ("old value", "f_RFP_p1.2"), ("old value", "f_RFP_p1.3"), ("old value", "f_RFP_p1.5"), ("depends", "f_RFP_p1.4"),
    }
    assert all(p["new"] == "f_ADD2_p1.4" and p["replaced"] == "f_RFP_p1.1" for p in got)
    assert len({p["id"] for p in got}) == 4 and G.pairs(facts) == got  # stable, each once


async def test_the_due_date_example():
    facts = due_date_facts()
    got = G.pairs(facts)
    checker = FakeChecker({"after June 10": 0.95, "signed original": 0.9, "site visit": 0.1, "Questions are due": 0.92})
    answers = await G.check_pairs(got, facts, checker, {})
    asked = {(tuple(ids), ins is G.DEPENDS) for _, ids, ins in checker.calls}
    assert asked == {(("f_RFP_p1.2", "f_RFP_p1.3", "f_RFP_p1.5"), False), (("f_RFP_p1.4",), True)}  # batched by new fact
    depends_new = next(n for n, _, ins in checker.calls if ins is G.DEPENDS)
    assert "June 24" in depends_new and "this replaces: Proposals due: June 10" in depends_new
    assert all(a["skipped"] == "" and a["at"] for a in answers.values())
    conflicts = G.settle(got, answers, facts, ["RFP", "ADD2"], None)
    by_fact = {c["fact_ids"][0]: c for c in conflicts}
    assert set(by_fact) == {"f_RFP_p1.2", "f_RFP_p1.3", "f_RFP_p1.4"}  # the site visit, answered 0.1, is untouched
    x = by_fact["f_RFP_p1.2"]
    assert (x["reason"], x["kind"], x["status"], x["doc_id"], x["closed_by"]) == ("old value elsewhere", "document", "open", "ADD2", "")
    assert x["id"] == conflict_id(x["fact_ids"], "old value elsewhere")
    assert x["options"][0]["label"] == "Update to June 24"
    assert x["options"][0]["changes"] == [{"op": "edit", "fact_id": "f_RFP_p1.2", "fields": {"text": "Proposals received after June 24 will not be opened"}}]
    assert x["options"][1]["changes"][0]["add_flag"] == "replaced"
    assert by_fact["f_RFP_p1.3"]["options"][0]["changes"][0]["fields"]["text"] == "Deliver one signed original by June 24"
    d = by_fact["f_RFP_p1.4"]
    assert d["reason"] == "depends on changed value" and [o["label"] for o in d["options"]] == ["Still correct", "Mark for review"]
    assert d["options"][1]["changes"][0]["add_flag"] == "unclear" and d["options"][0]["changes"] == []
    assert all(f["text"] == o["text"] for f, o in zip(due_date_facts(), facts))  # no fact's text was changed


def test_when_the_changed_value_is_not_a_single_value_the_option_marks_it_replaced():
    facts = [
        fact(1, "RFP", "p1.1", "Proposals due June 10, 2:00 pm", flags=["replaced"], replaced_by="f_ADD2_p1.4"),
        fact(1, "RFP", "p1.2", "Deliver the proposal by June 10"),
        fact(2, "ADD2", "p1.4", "Proposals due June 24, 4:00 pm"),
    ]
    got = G.pairs(facts)
    c = G.settle(got, {p["id"]: {"probability": 0.9, "skipped": ""} for p in got}, facts, ["RFP", "ADD2"])[0]
    assert [o["label"] for o in c["options"]] == ["Mark it replaced", "Keep it as it is"]


def test_the_review_band_only_marks_the_fact_that_may_be_out_of_date():
    facts = due_date_facts()
    got = G.pairs(facts)
    answers = {p["id"]: {"probability": 0.6 if p["old"] == "f_RFP_p1.5" else 0.3, "at": "x", "skipped": ""} for p in got}
    assert G.settle(got, answers, facts, ["RFP", "ADD2"]) == []
    stale = {f["fact_id"]: f["stale"] for f in facts if f["stale"]}
    assert stale == {"f_RFP_p1.5": "may conflict with f_ADD2_p1.4"} and G.REVIEW_BAND == 0.5
    edge = {p["id"]: {"probability": 0.7, "skipped": ""} for p in got}
    assert len(G.settle(got, edge, due_date_facts(), ["RFP", "ADD2"])) == 4  # at the threshold the ladder decides


async def test_a_skipped_check_is_recorded_and_asked_again():
    facts = due_date_facts()
    got = G.pairs(facts)
    none = await G.check_pairs(got, facts, None, {})
    assert {a["skipped"] for a in none.values()} == {"no checker"} and set(none) == {p["id"] for p in got}
    assert G.settle(got, none, facts, ["RFP", "ADD2"]) == []
    down = await G.check_pairs(got, facts, FakeChecker(fail=RuntimeError("down")), none)
    assert all("RuntimeError: down" in a["skipped"] for a in down.values())
    ok = FakeChecker({"after June 10": 0.95})
    answered = await G.check_pairs(got, facts, ok, down)
    assert all(a["skipped"] == "" for a in answered.values()) and ok.calls
    again = FakeChecker()
    assert await G.check_pairs(got, facts, again, answered) == answered and again.calls == []  # never asked twice


def test_levels_that_differ_are_a_levels_disagree_conflict():
    facts = [
        fact(1, "RFP", "p1.1", "Proposals due June 10, 2:00 pm", flags=["replaced"], replaced_by="f_ADD2_p1.4"),
        fact(3, "NOTES", "p1.1", "They told us proposals are due June 10", level=4),
        fact(2, "ADD2", "p1.4", "Proposals due June 24, 2:00 pm"),
    ]
    got = G.pairs(facts)
    [c] = G.settle(got, {p["id"]: {"probability": 0.9, "skipped": ""} for p in got}, facts, ["RFP", "ADD2", "NOTES"])
    assert c["reason"] == "levels disagree" and c["options"][-1]["question"] is True
    assert c["options"][1]["changes"][0]["fact_id"] == "f_ADD2_p1.4"  # relying on the note would mark the buyer's fact replaced


# --- the bid ----------------------------------------------------------------------------------------


def make_bid(tmp_path):
    bid = B.create(tmp_path, "Ulster", "deal-1")
    m = bid.manifest()
    rows = [(1, "RFP", "rfp", "2026-05-01", None), (2, "ADD2", "change-addendum", "2026-06-01", 2)]
    m["documents"] = [
        {"no": no, "doc_id": doc, "playbook": pb, "issue_date": date, "issue_number": n, "run": f"{doc}/run1", "status": "extracted"}
        for no, doc, pb, date, n in rows
    ]
    bid.save(m)
    for no, doc, *_ in rows:
        mine = [dict(f) for f in due_date_facts() if f["doc_id"] == doc]
        for f in mine:
            for k in ("doc_no", "level", "flags", "replaced_by", "stale", "relations"):
                f.pop(k)
        folder = tmp_path / doc / "run1"
        folder.mkdir(parents=True)
        (folder / "facts.json").write_text(json.dumps(mine))
        (folder / "units.json").write_text(json.dumps([{"id": c["id"], "kind": "sentence", "text": f["text"]} for f in mine for c in f["citations"]]))
        if doc == "ADD2":
            rel = {"units": [{"unit": "p1.4", "kind": "REPLACES", "targets": [{"doc_id": "RFP", "unit": "p1.1"}]}]}
            (folder / "relations.json").write_text(json.dumps(rel))
    return bid


async def test_settle_stores_the_answers_and_build_applies_them_without_a_model(tmp_path):
    bid = make_bid(tmp_path)
    plain = B.build(bid)
    assert {f["fact_id"]: f["flags"] for f in plain}["f_RFP_p1.1"] == ["replaced"] and json.loads((bid.folder / "conflicts.json").read_text()) == []
    client, checker = ScriptedClient(lambda r: "END|0"), FakeChecker({"after June 10": 0.95, "Questions are due": 0.92, "site visit": 0.1, "signed original": 0.6})
    steps = []
    facts = await B.settle(bid, client, checker, FAST, on_step=lambda *a: steps.append(a[1:3]))
    assert client.requests == [] and ("group", "done") in steps and ("pairs", "done") in steps
    stored = json.loads((bid.folder / "pairs.json").read_text())
    assert len(stored) == 4 and all(set(a) == {"probability", "at", "skipped"} for a in stored.values())
    assert json.loads((bid.folder / "groups.json").read_text())["categories"] == {}
    conflicts = json.loads((bid.folder / "conflicts.json").read_text())
    assert {(c["reason"], c["fact_ids"][0]) for c in conflicts} == {("old value elsewhere", "f_RFP_p1.2"), ("depends on changed value", "f_RFP_p1.4")}
    assert {f["fact_id"]: f["stale"] for f in facts}["f_RFP_p1.3"] == "may conflict with f_ADD2_p1.4"
    asked = len(checker.calls)
    assert B.build(bid) == facts  # deterministic, and no checker needed
    await B.settle(bid, client, checker, FAST)
    assert len(checker.calls) == asked  # nothing asked twice


async def test_settle_without_a_checker_records_every_pair_as_skipped_and_builds(tmp_path):
    bid = make_bid(tmp_path)
    facts = await B.settle(bid, None, None, FAST)
    stored = json.loads((bid.folder / "pairs.json").read_text())
    assert len(stored) == 4 and {a["skipped"] for a in stored.values()} == {"no checker"}
    assert json.loads((bid.folder / "conflicts.json").read_text()) == [] and len(facts) == 7
    checker = FakeChecker({"after June 10": 0.95})
    await B.settle(bid, None, checker, FAST)  # the skipped pairs are asked again
    assert len(checker.calls) == 2
    assert B.FACT_STEPS[-2:] == [B._apply_groups, B._apply_pairs]


def test_the_bid_run_command_settles(tmp_path, monkeypatch):
    import fact_extractor.cli as cli

    bid = make_bid(tmp_path)
    monkeypatch.setattr(cli, "load_env", lambda: None)  # a developer's .env must not give the test a key
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert cli.main(["bid", "run", bid.bid_id, "--store", str(tmp_path)]) == 0
    assert len(json.loads((bid.folder / "pairs.json").read_text())) == 4
