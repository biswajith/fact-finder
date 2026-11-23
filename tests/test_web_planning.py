"""Chat planning modes (direct, light, heavy), plan approval, and the Decisions API router and judge.
No API call is ever made."""

import json

import pytest
from langchain_openai.decisions import ChoiceAnswer, DecisionResponse, PredicateAnswer, Usage
from test_web_agent import ScriptedChat, call, types
from test_web_agent import svc, ws  # noqa: F401  (fixtures)

from fact_extractor.web import ModelUnavailable
from fact_extractor.web import agent as A
from fact_extractor.web import planning as P

NO_APPROVAL = ()


def planning(mode, verdict="approve", approve=("light", "heavy")):
    return P.Planning(P.FixedRouter(mode), P.FixedJudge(verdict), approve)


async def run(ws, svc, model, plan, text="hello"):
    return [e async for e in A.chat(ws, svc, model, text, plan)]


class Tools(ScriptedChat):
    """A ScriptedChat that also records the tool names offered on each call."""

    def __init__(self, *turns):
        super().__init__(*turns)
        self.tools: list[list[str]] = []

    async def stream(self, messages, tools):
        self.tools.append([t["function"]["name"] for t in tools])
        async for item in super().stream(messages, tools):
            yield item


class FakeDecisions:
    """Stands in for OpenAIDecisions: records each request, answers with a scripted answer or raises."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.requests: list[dict] = []

    async def ainvoke(self, request):
        self.requests.append(request)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return DecisionResponse(model="gpt-6-luna", answers={"q": answer}, usage=Usage(input_tokens=10))


def choice(value, options=P.MODES, confidence=0.9):
    rest = (1 - confidence) / (len(options) - 1)
    probs = {m: (confidence if m == value else rest) for m in options}
    return ChoiceAnswer(type="choice", choice=value, probabilities=probs, confidence=confidence)


def verdict(value, confidence=0.9):
    return choice(value, P.VERDICTS, confidence)


HEAVY_PLAN = '{"steps": ["Find the deadlines", "Check each against the schedule", "Answer"]}'
SHOWN = "Plan:\n1. Find the deadlines\n2. Check each against the schedule\n3. Answer"


# --- the Decisions router and judge ------------------------------------------------------------------


async def test_router_asks_one_choice_question_and_uses_a_confident_pick():
    fake = FakeDecisions(choice("heavy", confidence=0.8))
    route = await P.DecisionsRouter(client=fake).route("RECENT CONVERSATION\n(none)", "Check every deadline")
    assert (route.mode, route.source) == ("heavy", "router") and route.confidence == 0.8
    q = fake.requests[0]["questions"]["q"]
    assert set(q.choices) == set(P.MODES) and "data" in q.instructions
    assert [m.content for m in fake.requests[0]["input"]] == [
        "RECENT CONVERSATION\n(none)", "LATEST CUSTOMER MESSAGE\nCheck every deadline"]


async def test_router_unsure_takes_light_and_failure_takes_direct():
    unsure = await P.DecisionsRouter(client=FakeDecisions(choice("heavy", confidence=0.4))).route("c", "m")
    assert (unsure.mode, unsure.source) == ("light", "fallback") and "unsure" in unsure.note
    failed = await P.DecisionsRouter(client=FakeDecisions(RuntimeError("boom"))).route("c", "m")
    assert (failed.mode, failed.source) == ("direct", "fallback") and "boom" in failed.note
    odd = await P.DecisionsRouter(client=FakeDecisions(PredicateAnswer(type="predicate", probability=0.5))).route("c", "m")
    assert (odd.mode, odd.source) == ("direct", "fallback")


async def test_router_and_judge_without_a_key_raise_model_unavailable(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ModelUnavailable):
        await P.DecisionsRouter().route("c", "m")
    with pytest.raises(ModelUnavailable):
        await P.DecisionsRouter().judge("c", "Plan: 1) x", "yes")


async def test_judge_needs_a_confident_answer_to_approve():
    fake = FakeDecisions(verdict("approve"), verdict("approve", 0.5), RuntimeError("down"), verdict("cancel"))
    judge = P.DecisionsRouter(client=fake)
    assert (await judge.judge("c", "Plan: 1) x", "yes")).verdict == "approve"
    unsure = await judge.judge("c", "Plan: 1) x", "hmm")
    assert (unsure.verdict, unsure.source) == ("revise", "fallback")
    assert (await judge.judge("c", "Plan: 1) x", "yes")).verdict == "revise"  # a failure never approves
    assert (await judge.judge("c", "Plan: 1) x", "stop")).verdict == "cancel"
    req = fake.requests[0]
    assert set(req["questions"]["q"].choices) == set(P.VERDICTS)
    assert [m.content for m in req["input"]][1:] == ["PLAN\nPlan: 1) x", "CUSTOMER REPLY\nyes"]


def test_planning_from_env(monkeypatch):
    monkeypatch.delenv("FACT_EXTRACTOR_CHAT_PLANNING", raising=False)
    monkeypatch.delenv("FACT_EXTRACTOR_CHAT_PLAN_APPROVAL", raising=False)
    p = P.planning_from_env()
    assert isinstance(p.router, P.DecisionsRouter) and p.judge is p.router and p.approve == ("light", "heavy")
    for value, mode in (("off", "direct"), ("direct", "direct"), ("LIGHT", "light"), ("heavy", "heavy")):
        monkeypatch.setenv("FACT_EXTRACTOR_CHAT_PLANNING", value)
        r = P.planning_from_env().router
        assert isinstance(r, P.FixedRouter) and r.mode == mode
    for value, approve in (("heavy", ("heavy",)), ("off", ())):
        monkeypatch.setenv("FACT_EXTRACTOR_CHAT_PLAN_APPROVAL", value)
        assert P.planning_from_env().approve == approve
    monkeypatch.setenv("FACT_EXTRACTOR_CHAT_PLAN_APPROVAL", "sometimes")
    with pytest.raises(ValueError):
        P.planning_from_env()
    monkeypatch.setenv("FACT_EXTRACTOR_CHAT_PLANNING", "always")
    with pytest.raises(ValueError):
        P.planning_from_env()


# --- the plan helpers ----------------------------------------------------------------------------------


def test_parse_plan_reads_json_or_numbered_lines():
    assert P.parse_plan('Sure. {"steps": ["find deadlines", " ", "answer"]}') == ["find deadlines", "answer"]
    assert P.parse_plan("1. search\n2) edit\n- answer\nnot a step") == ["search", "edit", "answer"]
    assert P.parse_plan("no plan here") == []
    assert len(P.parse_plan(json.dumps({"steps": [f"s{i}" for i in range(30)]}))) == P.MAX_STEPS


def test_update_steps_marks_done_and_revises_the_rest():
    steps = [{"step": s, "done": False} for s in ("a", "b", "c")]
    P.update_steps(steps, [1], ["x", "y"])
    assert steps == [{"step": "a", "done": True}, {"step": "x", "done": False}, {"step": "y", "done": False}]
    with pytest.raises(ValueError):
        P.update_steps(steps, [9], None)
    with pytest.raises(ValueError):
        P.update_steps(steps, None, ["", "z"])


# --- modes without approval ------------------------------------------------------------------------------


async def test_no_planning_is_the_old_loop_and_stores_no_planning(ws, svc):
    events = await run(ws, svc, ScriptedChat(["Hi."]), None)
    assert types(events) == ["text", "done"] and "planning" not in events[-1]["message"]


async def test_direct_mode_records_the_route_and_never_asks(ws, svc):
    model = ScriptedChat(["Hi."])
    events = await run(ws, svc, model, planning("direct"))
    assert types(events) == ["plan", "text", "done"]
    assert events[0] == {"type": "plan", "mode": "direct", "source": "forced"}
    assert ws.chat()[-1]["planning"] == {"mode": "direct", "source": "forced"}
    assert P.LIGHT_PROMPT not in json.dumps(model.seen[0])


async def test_light_mode_without_approval_plans_inline_in_one_loop(ws, svc):
    model = ScriptedChat(["Plan: 1) look up 2) answer. ", call("search", query="deadline")], ["Done."])
    events = await run(ws, svc, model, planning("light", approve=NO_APPROVAL))
    assert len(model.seen) == 2  # the two loop rounds, no planning call
    state = model.seen[0][-2]
    assert state["role"] == "system" and "facts" in state["content"] and P.LIGHT_PROMPT in state["content"]
    assert model.seen[0][-1]["role"] == "user"
    assert events[-1]["message"]["text"].startswith("Plan: 1)")


async def test_heavy_mode_without_approval_plans_then_executes_with_update_plan(ws, svc):
    model = Tools(
        [HEAVY_PLAN],  # planning call
        [call("search", query="deadline"), call("update_plan", "call_2", done=[1])],
        [call("update_plan", "call_3", done=[2], revise=["Answer with the one mismatch"])],
        ["One deadline does not match [f_d3]."],
    )
    events = await run(ws, svc, model, planning("heavy", approve=NO_APPROVAL), "Check every deadline")
    assert model.tools[0] == [] and "update_plan" in model.tools[1]
    assert "update_plan" not in [t["function"]["name"] for t in A.TOOL_SPECS]
    assert "JSON only" in model.seen[0][-1]["content"]
    assert model.seen[1][-2] == {"role": "assistant", "content": SHOWN}
    assert model.seen[1][-1]["role"] == "system" and "1. Find the deadlines" in model.seen[1][-1]["content"]
    assert events[0] == {"type": "text", "delta": SHOWN + "\n\n"}
    assert sum(1 for e in events if e["type"] == "plan") == 3  # the start, then after each update_plan
    final = events[-1]["message"]
    assert final["planning"]["steps"] == [
        {"step": "Find the deadlines", "done": True},
        {"step": "Check each against the schedule", "done": True},
        {"step": "Answer with the one mismatch", "done": False},
    ]
    assert final["text"].endswith("One deadline does not match [f_d3].")
    assert "status" not in final["planning"]


async def test_plan_cannot_be_reworded_before_any_tool_result(ws, svc):
    plan = planning("heavy")
    await run(ws, svc, Tools([HEAVY_PLAN]), plan, "Check every deadline")
    model = Tools(
        [call("update_plan", revise=["Shorter step one", "Answer"])],  # rewording straight away: refused
        [call("search", "call_2", query="deadline"), call("update_plan", "call_3", done=[1])],
        [call("update_plan", "call_4", revise=["Answer"])],  # after a lookup: allowed
        ["Done."],
    )
    events = await run(ws, svc, model, plan, "go ahead")
    plan_tools = [e for e in events if e["type"] == "tool" and e["name"] == "update_plan"]
    assert [e["ok"] for e in plan_tools] == [False, True, True]
    assert "revise only after" in plan_tools[0]["label"]
    final = events[-1]["message"]["planning"]["steps"]
    assert final == [{"step": "Find the deadlines", "done": True}, {"step": "Answer", "done": False}]
    assert "never to reword" in model.seen[0][-1]["content"]


async def test_heavy_mode_without_usable_steps_falls_back_to_light(ws, svc):
    model = ScriptedChat(["I will just do it."], ["Answer."])
    events = await run(ws, svc, model, planning("heavy", approve=NO_APPROVAL))
    final = events[-1]["message"]
    assert final["planning"]["mode"] == "light" and "ran light" in final["planning"]["note"]
    assert model.seen[1][-1] == {"role": "system", "content": P.LIGHT_PROMPT}


async def test_heavy_mode_gets_more_rounds(ws, svc):
    loop = [[call("search", f"c{i}", query="x")] for i in range(A.HEAVY_ROUNDS + 1)]
    events = await run(ws, svc, ScriptedChat(['{"steps": ["search", "answer"]}'], *loop),
                       planning("heavy", approve=NO_APPROVAL))
    assert sum(1 for e in events if e["type"] == "tool") == A.HEAVY_ROUNDS
    assert f"after {A.HEAVY_ROUNDS} rounds" in events[-2]["message"]


async def test_update_plan_outside_heavy_mode_is_an_error_for_the_model(ws, svc):
    events = await run(ws, svc, ScriptedChat([call("update_plan", done=[1])], ["ok"]),
                       planning("light", approve=NO_APPROVAL))
    tool = next(e for e in events if e["type"] == "tool")
    assert tool["ok"] is False and "no plan" in tool["label"]


# --- approval -------------------------------------------------------------------------------------------


async def test_light_plan_is_shown_and_nothing_runs_until_approved(ws, svc):
    model = Tools(["Plan: 1) find the deadline 2) change it to March 5"])
    events = await run(ws, svc, model, planning("light"), "Move the deadline and check the summary")
    assert model.tools == [[]]  # one planning call, no tools offered, no loop
    assert P.LIGHT_PLAN_PROMPT == model.seen[0][-1]["content"]
    final = events[-1]["message"]
    assert final["text"] == f"Plan: 1) find the deadline 2) change it to March 5\n\n{P.ASK_APPROVAL}"
    assert final["tools"] == [] and final["planning"]["status"] == P.AWAITING
    assert final["planning"]["plan_text"].startswith("Plan: 1)")
    assert not [e for e in events if e["type"] in ("tool", "changed")]


async def test_approved_light_plan_runs_with_the_plan_in_history(ws, svc):
    plan = planning("light")
    await run(ws, svc, ScriptedChat(["Plan: 1) find it 2) fix it"]), plan, "Fix the deadline")
    model = Tools([call("search", query="deadline")], ["Fixed."])
    events = await run(ws, svc, model, plan, "yes, go ahead")
    sent = model.seen[0]
    assert sent[-3] == {"role": "user", "content": "yes, go ahead"}
    assert sent[-2:] == [{"role": "system", "content": P.APPROVED_PROMPT},
                         {"role": "system", "content": P.APPROVED_LIGHT_PROMPT}]
    assert any(m["role"] == "assistant" and "Plan: 1) find it" in (m["content"] or "") for m in sent)
    assert "update_plan" not in model.tools[0]
    final = events[-1]["message"]
    assert final["text"] == "Fixed." and final["planning"]["status"] == "approved"
    assert final["planning"]["source"] == "plan" and final["planning"]["feedback"]["verdict"] == "approve"


async def test_approved_heavy_plan_runs_its_stored_steps(ws, svc):
    plan = planning("heavy")
    first = await run(ws, svc, Tools([HEAVY_PLAN]), plan, "Check every deadline")
    assert first[-1]["message"]["text"] == f"{SHOWN}\n\n{P.ASK_APPROVAL}"
    model = Tools([call("update_plan", done=[1, 2])], ["All match."])
    events = await run(ws, svc, model, plan, "ok")
    assert "update_plan" in model.tools[0]  # no new planning call: the stored plan runs
    assert "1. Find the deadlines" in model.seen[0][-1]["content"]
    final = events[-1]["message"]
    assert [s["done"] for s in final["planning"]["steps"]] == [True, True, False]
    assert final["planning"]["status"] == "approved" and final["text"] == "All match."


async def test_revise_writes_the_plan_again_and_asks_again(ws, svc):
    plan = planning("heavy", verdict="revise")
    await run(ws, svc, Tools([HEAVY_PLAN]), plan, "Check every deadline")
    model = Tools(['{"steps": ["Find the deadlines", "Answer"]}'])
    events = await run(ws, svc, model, plan, "skip the schedule check")
    assert model.tools == [[]]
    assert [m["content"] for m in model.seen[0][-2:]][0] == P.REVISE_PROMPT
    final = events[-1]["message"]
    assert final["text"] == f"Plan:\n1. Find the deadlines\n2. Answer\n\n{P.ASK_APPROVAL}"
    assert final["planning"]["status"] == P.AWAITING and final["planning"]["feedback"]["verdict"] == "revise"


async def test_cancel_makes_no_model_call(ws, svc):
    plan = planning("light", verdict="cancel")
    await run(ws, svc, ScriptedChat(["Plan: 1) delete all risks"]), plan, "Remove the risks")
    model = ScriptedChat()
    events = await run(ws, svc, model, plan, "no, leave it")
    assert model.seen == []
    final = events[-1]["message"]
    assert final["text"] == P.CANCELLED and final["planning"]["status"] == "cancelled"
    assert P.pending_plan(ws.chat()) is None


async def test_new_request_forgets_the_plan_and_is_routed_afresh(ws, svc):
    plan = P.Planning(P.FixedRouter("light"), P.FixedJudge("new_request"))
    await run(ws, svc, ScriptedChat(["Plan: 1) a 2) b"]), plan, "Do a and b")
    plan.router = P.FixedRouter("direct")
    events = await run(ws, svc, ScriptedChat(["The deadline is March 3."]), plan, "when is it due?")
    final = events[-1]["message"]
    assert final["text"] == "The deadline is March 3."
    assert final["planning"]["source"] == "forced" and final["planning"]["feedback"]["verdict"] == "new_request"


async def test_only_the_last_message_can_hold_a_waiting_plan():
    asking = {"role": "assistant", "planning": {"mode": "light", "status": P.AWAITING, "plan_text": "Plan: 1) x"}}
    assert P.pending_plan([asking]).plan_text == "Plan: 1) x"
    assert P.pending_plan([asking, {"role": "user"}]) is None
    assert P.pending_plan([{"role": "assistant", "planning": {"mode": "light", "status": "approved"}}]) is None
    assert P.pending_plan([]) is None


async def test_approval_only_for_the_listed_modes(ws, svc):
    plan = planning("light", approve=("heavy",))
    model = ScriptedChat(["Plan: 1) x. Done."])
    events = await run(ws, svc, model, plan)
    assert "status" not in events[-1]["message"]["planning"] and len(model.seen) == 1


# --- the router in the chat --------------------------------------------------------------------------------


async def test_router_sees_recent_conversation_and_state(ws, svc):
    fake = FakeDecisions(choice("direct"), choice("direct"))
    plan = P.Planning(P.DecisionsRouter(client=fake))
    await run(ws, svc, ScriptedChat(["first answer"]), plan, "first")
    await run(ws, svc, ScriptedChat(["second answer"]), plan, "second")
    context = fake.requests[1]["input"][0].content
    assert "USER: first" in context and "ASSISTANT: first answer" in context and "facts" in context
    assert fake.requests[1]["input"][1].content.endswith("second")


async def test_a_router_that_raises_still_gets_an_answer(ws, svc):
    class Broken:
        async def route(self, context, user_text):
            raise RuntimeError("down")

    events = await run(ws, svc, ScriptedChat(["Hi."]), P.Planning(Broken()))
    final = events[-1]["message"]
    assert final["text"] == "Hi." and final["planning"]["source"] == "fallback" and "down" in final["planning"]["note"]


async def test_planning_call_keeps_the_heavy_tool_list_but_refuses_tools(ws, svc):
    class Refusing(ScriptedChat):
        async def stream(self, messages, tools, allow_tools=True):
            self.calls = getattr(self, "calls", []) + [([t["function"]["name"] for t in tools], allow_tools)]
            async for item in super().stream(messages, tools):
                yield item

    model = Refusing([HEAVY_PLAN], ["Done."])
    await run(ws, svc, model, planning("heavy", approve=NO_APPROVAL))
    (plan_tools, plan_allowed), (loop_tools, loop_allowed) = model.calls
    assert plan_tools == loop_tools and "update_plan" in plan_tools  # one prefix for both calls
    assert (plan_allowed, loop_allowed) == (False, True)


async def test_router_trusts_clear_probabilities_when_confidence_is_just_under_the_cut_off():
    """direct at 0.72 against 0.25 with confidence 0.58 runs direct; the same confidence with a close
    split, or a clear split with a confidence far below the cut-off, still falls back to light."""
    def answer(probs, confidence, pick="direct"):
        return ChoiceAnswer(type="choice", choice=pick, probabilities=probs, confidence=confidence)

    clear = {"direct": 0.72, "light": 0.25, "heavy": 0.03}
    r = await P.DecisionsRouter(client=FakeDecisions(answer(clear, 0.58))).route("c", "m")
    assert (r.mode, r.source) == ("direct", "router") and "trusted the probabilities" in r.note

    close = {"direct": 0.5, "light": 0.45, "heavy": 0.05}
    r = await P.DecisionsRouter(client=FakeDecisions(answer(close, 0.58))).route("c", "m")
    assert (r.mode, r.source) == ("light", "fallback")

    r = await P.DecisionsRouter(client=FakeDecisions(answer(clear, 0.4))).route("c", "m")
    assert (r.mode, r.source) == ("light", "fallback")
