"""Added facts are checked against existing ones (consistency.py). No API call is ever made."""

import pytest
from langchain_openai.decisions import DecisionResponse, PredicateAnswer, Usage
from test_web_agent import ScriptedChat, call, types
from test_web_agent import svc, ws  # noqa: F401  (fixtures)

from fact_extractor.web import agent as A
from fact_extractor.web.consistency import ConsistencyChecker


class FakePredicates:
    """Stands in for OpenAIDecisions: answers every predicate with the probability `by_text` gives for the
    existing fact's text in its instructions (0.05 when none matches), or raises."""

    def __init__(self, by_text=None, fail=None):
        self.by_text = by_text or {}
        self.fail = fail
        self.requests = []

    async def ainvoke(self, request):
        self.requests.append(request)
        if self.fail:
            raise self.fail
        answers = {}
        for name, q in request["questions"].items():
            p = next((v for k, v in self.by_text.items() if k in q.instructions), 0.05)
            answers[name] = PredicateAnswer(type="predicate", probability=p)
        return DecisionResponse(model="gpt-6-luna", answers=answers, usage=Usage(input_tokens=300))


def added(ws, text, category="D"):
    return ws.add({"category": category, "text": text}, source="chat")


async def test_a_likely_contradiction_raises_a_conflict_with_working_options(ws):
    new = added(ws, "The buyer moved the bid deadline to March 20")
    fake = FakePredicates({"Bids due March 3": 0.92})
    result = await ConsistencyChecker(client=fake).check(ws, new, await A.related_facts(ws, new), "chat")
    assert [f.fact_id for f in result.findings if f.probability >= 0.7] == ["f_d1"]
    assert len(result.conflict_ids) == 1 and result.call["input_tokens"] == 300
    c = ws.state().conflict(result.conflict_ids[0])
    assert c["status"] == "open" and c["fact_ids"] == [new["fact_id"], "f_d1"] and "92% likely" in c["description"]
    assert [len(o["changes"]) for o in c["options"]] == [1, 1, 0]  # every option does what it says
    q = fake.requests[0]
    assert q["input"][0].content == "NEW: The buyer moved the bid deadline to March 20"
    assert any("Bids due March 3" in x.instructions for x in q["questions"].values())

    ws.resolve(c["id"], option=0)  # the added fact applies: the old one is kept, marked replaced
    old = ws.state().get("f_d1")
    assert "replaced" in old["flags"] and new["fact_id"] in old["note"]
    assert ws.state().get(new["fact_id"]) is not None


async def test_the_existing_fact_can_win(ws):
    new = added(ws, "Bids are due March 30")
    result = await ConsistencyChecker(client=FakePredicates({"Bids due March 3": 0.95})).check(
        ws, new, await A.related_facts(ws, new), "ui")
    ws.resolve(result.conflict_ids[0], option=1)
    assert ws.state().get(new["fact_id"])["deleted"] and "replaced" not in ws.state().get("f_d1")["flags"]


async def test_no_conflict_below_the_threshold_or_without_related_facts(ws):
    new = added(ws, "The buyer may extend the bid deadline with notice")
    result = await ConsistencyChecker(client=FakePredicates({"Bids due March 3": 0.4})).check(
        ws, new, await A.related_facts(ws, new), "chat")
    assert result.findings and result.conflict_ids == [] and ws.state().conflicts == [
        c for c in ws.state().conflicts if c["kind"] != "raised"]
    lonely = added(ws, "zzqx")
    fake = FakePredicates()
    assert (await ConsistencyChecker(client=fake).check(ws, lonely, [], "chat")).findings == [] and fake.requests == []


async def test_a_failed_check_is_skipped_and_the_fact_stays(ws):
    new = added(ws, "Bids due March 20")
    result = await ConsistencyChecker(client=FakePredicates(fail=RuntimeError("down"))).check(
        ws, new, await A.related_facts(ws, new), "chat")
    assert "down" in result.skipped and result.conflict_ids == [] and ws.state().get(new["fact_id"])
    assert result.record()["check_skipped"].startswith("RuntimeError")


async def test_missing_key_skips_the_check(ws, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    new = added(ws, "Bids due March 20")
    result = await ConsistencyChecker().check(ws, new, await A.related_facts(ws, new), "chat")
    assert "OPENAI_API_KEY" in result.skipped


async def test_related_facts_leave_out_itself_and_replaced_facts(ws):
    new = added(ws, "Bids due March 20")
    assert "f_d1" in [f["fact_id"] for f in await A.related_facts(ws, new)]
    assert new["fact_id"] not in [f["fact_id"] for f in await A.related_facts(ws, new)]
    ws.edit("f_d1", {"flags": ["replaced"]})
    assert "f_d1" not in [f["fact_id"] for f in await A.related_facts(ws, new)]


async def test_chat_add_fact_reports_the_conflict_and_logs_the_check(ws, svc):
    checker = ConsistencyChecker(client=FakePredicates({"Bids due March 3": 0.9}))
    model = ScriptedChat([call("add_fact", category="D", text="The buyer moved the bid deadline to March 20")], ["Raised."])
    events = [e async for e in A.chat(ws, svc, model, "They moved the deadline to March 20", None, checker)]
    assert "conflict" in types(events)
    tool_result = model.seen[1][-1]["content"]
    assert "conflicts_raised" in tool_result and "do not resolve it yourself" in tool_result
    log = ws.chat_events(ws.chat_session())
    check = next(e for e in log if e["event"] == "consistency_check")
    assert check["conflicts_raised"] and check["call"]["cost_usd"] == pytest.approx(300 * 0.10 / 1e6)
    assert log[-1]["totals"]["decisions_calls"] == 1
    assert events[-1]["message"]["conflict_ids"] == check["conflicts_raised"]


async def test_without_a_checker_nothing_is_checked(ws, svc):
    model = ScriptedChat([call("add_fact", category="D", text="Bids due March 20")], ["ok"])
    events = [e async for e in A.chat(ws, svc, model, "x")]
    assert "conflict" not in types(events) and "conflicts_raised" not in model.seen[1][-1]["content"]


async def test_chat_edit_lists_facts_that_may_still_state_the_old_value(ws, svc):
    ws.add({"category": "D", "text": "Email bids by March 3 to the clerk"}, source="ui")
    checker = ConsistencyChecker(client=FakePredicates({"Email bids by March 3": 0.95}))
    model = ScriptedChat([call("edit_fact", fact_id="f_d1", text="Bids due March 20", reason="moved")], ["Done."])
    events = [e async for e in A.chat(ws, svc, model, "The deadline moved to March 20", None, checker)]
    result = model.seen[1][-1]["content"]
    assert "may_be_out_of_date" in result and "Email bids by March 3" in result and "update it" in result
    assert "conflict" not in types(events) and ws.state().conflicts == [c for c in ws.state().conflicts if c["kind"] != "raised"]
    check = next(e for e in ws.chat_events(ws.chat_session()) if e["event"] == "consistency_check")
    assert check["kind"] == "edited" and not check["conflicts_raised"]


async def test_chat_edit_without_text_is_not_checked(ws, svc):
    fake = FakePredicates({"Bids due March 3": 0.95})
    model = ScriptedChat([call("edit_fact", fact_id="f_d1", note="checked", reason="r")], ["ok"])
    [e async for e in A.chat(ws, svc, model, "x", None, ConsistencyChecker(client=fake))]
    assert fake.requests == []


async def test_screen_edit_raises_a_conflict_whose_options_work(ws):
    other = ws.add({"category": "D", "text": "Email bids by March 3 to the clerk"}, source="ui")
    edited = ws.edit("f_d1", {"text": "Bids due March 20"}, "", source="ui")
    result = await ConsistencyChecker(client=FakePredicates({"Email bids by March 3": 0.9})).check(
        ws, edited, await A.related_facts(ws, edited), "ui", kind="edited")
    c = ws.state().conflict(result.conflict_ids[0])
    assert c["title"].startswith("Edited fact") and [len(o["changes"]) for o in c["options"]] == [1, 0]
    ws.resolve(c["id"], option=0)
    assert "replaced" in ws.state().get(other["fact_id"])["flags"]
