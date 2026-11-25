"""chateval.py: chat cases played against a scripted model and scored. No API call is ever made."""

import json

import pytest
from test_web_agent import ScriptedChat, call
from test_web_summaries import MORE, Scripted
from test_web_workspace import make_run

from fact_extractor import chateval as E
from fact_extractor.web import agent as A
from fact_extractor.web import planning as P
from fact_extractor.web.summaries import SummaryService

CASES = """
bid: b
cases:
  - id: fix-date
    kind: change
    say: "The bids are due March 5, not March 3."
    expect:
      edits:
        - {doc: 1, text: "Bids due March 3", has: ["March 5"], lacks: ["March 3"]}
  - id: ask-first
    kind: ambiguous
    say: "Change the date."
    expect: {asks: true}
"""


def expect(**kw):
    return {"answer": [], "asks": False, "edits": [], "deletes": [], "may_edit": [], "adds": {}, "resolves": {}, **kw}


def case(**kw):
    return E.Case("c", "change", kw.pop("say", "Fix it"), {}, **kw)


@pytest.fixture
def facts_path(tmp_path):
    """A function that makes a fresh run each time it is called, so no conversation sees another's changes."""
    made = []

    def fresh():
        made.append(1)
        return make_run(tmp_path, name=f"doc/run{len(made)}", facts=MORE) / "facts.json"

    return fresh


def planning(mode, verdict="approve"):
    return P.Planning(P.FixedRouter(mode), P.FixedJudge(verdict), ("light", "heavy"))


async def play(c, x, facts_path, model, plan=None, mode="direct"):
    return await E.converse(c, x, mode, facts_path(), A.chat, SummaryService(Scripted()), model, plan)


EDIT = [call("edit_fact", fact_id="f_d1", text="Bids due March 5", reason="customer said so", values_removed=True)]
WANT = expect(edits=[{"fact_id": "f_d1", "text": "Bids due March 3", "has": ["March 5"], "lacks": ["March 3"]}])


def test_load_reads_cases_and_refuses_a_wrong_file(tmp_path):
    path = tmp_path / "cases.yaml"
    path.write_text(CASES)
    bid, cases = E.load(path)
    assert bid == "b" and [c.id for c in cases] == ["fix-date", "ask-first"] and cases[1].expect == {"asks": True}
    path.write_text("bid: b\ncases:\n  - {id: x, kind: change, say: hi, expect: {edit: []}}")
    with pytest.raises(E.CaseError, match="unknown expectation edit"):
        E.load(path)
    path.write_text("bid: b\ncases:\n  - {id: x, kind: change}")
    with pytest.raises(E.CaseError, match="lacks say"):
        E.load(path)


def test_locate_needs_exactly_one_fact():
    facts = [{"fact_id": "f_1", "doc_no": 1, "text": "Bids due March 3"}, {"fact_id": "f_2", "doc_no": 1, "text": "Bids due March 5"},
             {"fact_id": "f_3", "doc_no": 2, "text": "Bids due March 3"}]
    assert E.locate(facts, {"doc": 2, "text": "bids due"}) == "f_3"
    with pytest.raises(E.CaseError, match="2 facts"):
        E.locate(facts, {"doc": 1, "text": "Bids due"})
    with pytest.raises(E.CaseError, match="0 facts"):
        E.locate(facts, {"doc": 3, "text": "Bids due"})


async def test_a_direct_edit_passes_in_one_message(facts_path):
    res = await play(case(), WANT, facts_path, ScriptedChat(EDIT, ["Changed [f_d1]."]))
    assert res.passed and res.failed == [] and res.messages == 1 and res.plans_waited == 0 and res.tools == 1
    assert res.routed == ["direct/-"] and res.changes[0]["op"] == "edit" and res.llm_calls == 2


async def test_an_edit_nobody_asked_for_fails_and_says_which(facts_path):
    model = ScriptedChat([*EDIT, call("edit_fact", "call_2", fact_id="f_d2", text="Bids due March 6", values_removed=True)], ["Done."])
    res = await play(case(), WANT, facts_path, model)
    assert not res.passed and len(res.failed) == 1 and "edited f_d2, which was not asked for" in res.failed[0]
    missing = await play(case(), WANT, facts_path, ScriptedChat(["Nothing to do."]))
    assert any("did not edit f_d1" in f for f in missing.failed)


async def test_a_plan_that_waits_is_approved_and_counted(facts_path):
    model = ScriptedChat(['{"steps": [{"step": "Change the due date"}]}'], EDIT, ["Changed [f_d1]."])
    res = await play(case(), WANT, facts_path, model, planning("light"), "light")
    assert res.passed and res.messages == 2 and res.plans_waited == 1 and res.questions == 0
    assert [t["customer"] for t in res.turns] == ["Fix it", E.APPROVE] and res.turns[0]["status"] == P.AWAITING


async def test_a_needless_question_costs_a_message_but_can_still_pass(facts_path):
    model = ScriptedChat(["Which date do you mean?"], EDIT, ["Changed [f_d1]."])
    res = await play(case(), WANT, facts_path, model)
    assert res.passed and res.messages == 2 and res.questions == 1 and res.turns[1]["customer"] == E.INSIST


async def test_a_case_that_expects_a_question(facts_path):
    asked = await play(case(), expect(asks=True), facts_path, ScriptedChat(["Which date do you mean?"]))
    assert asked.passed and asked.messages == 1 and asked.questions == 1
    guessed = await play(case(), expect(asks=True), facts_path, ScriptedChat(EDIT, ["Changed [f_d1]."]))
    assert "did not ask before changing facts" in guessed.failed and any("not asked for" in f for f in guessed.failed)
    model = ScriptedChat(["Which date do you mean?"], EDIT, ["Changed [f_d1]."])
    then = await play(case(if_asked="The March 3 one."), {**WANT, "asks": True}, facts_path, model)
    assert then.passed and [t["customer"] for t in then.turns] == ["Fix it", "The March 3 one."]


async def test_the_reply_and_added_facts_are_checked(facts_path):
    x = expect(answer=["March 3", "email"], adds={"min": 1, "max": 1, "has": ["April"]})
    res = await play(case(), x, facts_path, ScriptedChat(["Bids are due March 3."]))
    assert res.failed == ["the reply does not say /email/", "added 0 facts, expected 1"]


async def test_run_plays_every_case_in_every_mode_on_a_copy_of_the_bid(tmp_path):
    store = tmp_path / "runs"
    bid = store / "_bids" / "b"
    bid.mkdir(parents=True)
    (bid / "facts.json").write_text(json.dumps([{**f, "doc_no": 1} for f in MORE]))
    (bid / "bid.json").write_text(json.dumps({"bid_id": "b", "documents": []}))
    cases = tmp_path / "cases.yaml"
    cases.write_text(CASES)

    class ByMessage:
        """Edits when asked to fix the date, asks when told only to change it."""

        async def stream(self, messages, tools):
            if any(m.get("role") == "tool" for m in messages):
                yield "Changed [f_d1]."
            elif "March 5" in messages[-1]["content"]:
                yield EDIT[0]
            else:
                yield "Which date do you mean?"

    out = tmp_path / "out"
    results = await E.run(store, cases, modes=("direct",), out=out,
                          models=lambda: (A.chat, SummaryService(Scripted()), ByMessage(), None))
    assert [(r.case, r.mode, r.passed) for r in results] == [("fix-date", "direct", True), ("ask-first", "direct", True)]
    assert not (bid / "workspace").exists()  # the stored bid was not touched
    assert json.loads((out / "results.json").read_text())[0]["changes"][0]["fact_id"] == "f_d1"
    assert (out / "logs" / "fix-date.direct.1").is_dir()
    text = E.report(results)
    assert "direct          2/2" in text and "WHAT FAILED" not in text and "fix-date" in text
    assert "2 cases for bid b" in E.listing(store, cases)


async def test_a_waiting_plan_counts_as_asking_and_an_edit_that_changes_nothing_is_not_an_edit(facts_path):
    plan = await play(case(), expect(asks=True), facts_path, ScriptedChat(['{"steps": [{"step": "Change the March 3 date"}]}']),
                      planning("light"), "light")
    assert plan.passed and plan.messages == 1 and plan.plans_waited == 1 and plan.changes == []
    same = [call("edit_fact", fact_id="f_d2", text="Bids due March 5")]
    res = await play(case(), expect(), facts_path, ScriptedChat(same, ["Nothing changed."]))
    assert res.passed and res.changes[0]["fact_id"] == "f_d2"


async def test_after_the_customer_answered_a_plan_is_approved(facts_path):
    plan = '{"steps": [{"step": "Change the March 3 date"}]}'
    model = ScriptedChat([plan], [plan], EDIT, ["Changed [f_d1]."])
    res = await play(case(if_asked="The March 3 one."), WANT, facts_path, model, planning("light", "revise"), "light")
    assert [t["customer"] for t in res.turns][:2] == ["Fix it", E.APPROVE]  # a case that expects no question approves at once
    model = ScriptedChat([plan], [plan])
    res = await play(case(if_asked="The March 3 one."), {**WANT, "asks": True}, facts_path, model, planning("light", "revise"), "light")
    assert [t["customer"] for t in res.turns] == ["Fix it", "The March 3 one.", E.APPROVE, E.APPROVE, E.APPROVE]
