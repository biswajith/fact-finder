"""Chat sessions and their event logs (chatlog.py). No API call is ever made."""

from types import SimpleNamespace

import pytest
from test_web_agent import ScriptedChat, call
from test_web_agent import svc, ws  # noqa: F401  (fixtures)
from test_web_planning import HEAVY_PLAN, FakeDecisions, choice, verdict

from fact_extractor.web import agent as A
from fact_extractor.web import planning as P
from fact_extractor.web.chatlog import CallUsage
from fact_extractor.web.workspace import NotFound


async def run(ws, svc, model, plan=None, text="hello"):
    return [e async for e in A.chat(ws, svc, model, text, plan)]


def kinds(events):
    return [e["event"] for e in events]


async def test_a_session_runs_until_the_chat_is_cleared(ws, svc):
    await run(ws, svc, ScriptedChat(["one"]))
    await run(ws, svc, ScriptedChat(["two"]))
    first = ws.chat_session()
    assert first.startswith("s_") and len(first) == 14
    assert {m["session_id"] for m in ws.chat()} == {first}
    assert len({m["turn_id"] for m in ws.chat()}) == 2  # one turn id per customer message, shared by its reply
    ws.clear_chat()
    await run(ws, svc, ScriptedChat(["three"]))
    second = ws.chat_session()
    assert second != first
    sessions = ws.chat_sessions()
    assert [s["session_id"] for s in sessions] == [second, first]  # newest first, the old log is kept
    assert [s["turns"] for s in sessions] == [1, 2] and [s["current"] for s in sessions] == [True, False]
    assert kinds(ws.chat_events(first)).count("user_message") == 2


async def test_a_turn_logs_message_calls_tools_reply_and_totals(ws, svc):
    class Counted(ScriptedChat):
        async def stream(self, messages, tools):
            async for item in super().stream(messages, tools):
                yield item
            yield CallUsage(1000, 800, 20, "m")

    model = Counted([call("search", queries=["bids", "questions"]), call("get_fact", "c2", fact_id="f_nope")], ["Done."])
    events = await run(ws, svc, model, text="When are bids due?")
    assert events[-1]["message"]["text"] == "Done."  # usage never reaches the text
    log = ws.chat_events(ws.chat_session())
    assert kinds(log) == ["user_message", "llm_call", "tool", "tool", "llm_call", "assistant_message", "turn_end"]
    assert log[0]["text"] == "When are bids due?"
    first = log[1]
    assert first["purpose"] == "loop" and first["round"] == 1 and first["tools_allowed"] is True
    assert [c["name"] for c in first["tool_calls"]] == ["search", "get_fact"]
    assert first["tool_calls"][0]["args"] == {"queries": ["bids", "questions"]}
    assert (first["input_tokens"], first["cached_tokens"], first["output_tokens"]) == (1000, 800, 20)
    assert log[2]["name"] == "search" and log[2]["ok"] and log[3]["ok"] is False
    assert log[5]["text"] == "Done." and log[5]["tools"] == 2
    totals = log[-1]["totals"]
    assert (totals["llm_calls"], totals["tool_calls"], totals["input_tokens"], totals["cached_tokens"]) == (2, 2, 2000, 1600)
    assert [e["seq"] for e in log] == list(range(1, 8)) and len({e["turn_id"] for e in log}) == 1
    assert ws.chat_sessions()[0]["totals"]["llm_calls"] == 2


async def test_planning_turns_log_route_plan_feedback_and_decisions_calls(ws, svc):
    fake = FakeDecisions(choice("heavy"), verdict("approve"))
    decisions = P.DecisionsRouter(client=fake)
    plan = P.Planning(decisions, decisions)
    await run(ws, svc, ScriptedChat([HEAVY_PLAN]), plan, "Check every deadline")
    await run(ws, svc, ScriptedChat([call("update_plan", done=[1])], ["All match."]), plan, "go ahead")
    log = ws.chat_events(ws.chat_session())
    first, second = [[e for e in log if e["turn_id"] == t] for t in dict.fromkeys(e["turn_id"] for e in log)]
    assert kinds(first) == ["user_message", "route", "llm_call", "plan", "assistant_message", "turn_end"]
    route = first[1]
    assert route["mode"] == "heavy" and route["source"] == "router" and route["call"]["input_tokens"] == 10
    assert first[2]["purpose"] == "plan_heavy" and first[2]["tools_allowed"] is False
    assert first[3]["status"] == P.AWAITING and len(first[3]["steps"]) == 3
    assert first[-1]["totals"]["decisions_calls"] == 1
    assert kinds(second)[:5] == ["user_message", "feedback", "route", "plan", "llm_call"]
    fb = second[1]
    assert fb["verdict"] == "approve" and fb["plan"].startswith("Plan:\n1.") and fb["call"]["model"]
    assert second[2]["source"] == "plan"
    assert kinds(second).count("plan") == 2  # the approved plan, then the update after update_plan
    assert second[-2]["planning"]["status"] == "approved"


async def test_a_failing_log_never_breaks_the_chat(ws, svc, monkeypatch):
    def broken(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(ws, "append_chat_events", broken)
    events = await run(ws, svc, ScriptedChat(["Hi."]))
    assert events[-1]["message"]["text"] == "Hi."


def test_bad_session_ids_are_not_found(ws):
    for sid in ("../../etc", "s_000000000000", "nope"):
        with pytest.raises(NotFound):
            ws.chat_events(sid)


async def test_openai_model_reports_usage_last(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    sent = {}
    usage = SimpleNamespace(prompt_tokens=500, completion_tokens=7,
                            prompt_tokens_details=SimpleNamespace(cached_tokens=400))
    chunks = [SimpleNamespace(usage=None, choices=[SimpleNamespace(delta=SimpleNamespace(content="hi", tool_calls=None))]),
              SimpleNamespace(usage=usage, choices=[])]

    async def create(**kw):
        sent.update(kw)

        async def gen():
            for c in chunks:
                yield c
        return gen()

    model = A.OpenAIChatModel()
    model._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    out = [x async for x in model.stream([{"role": "user", "content": "x"}], [])]
    assert sent["stream_options"] == {"include_usage": True}
    assert out[0] == "hi" and isinstance(out[-1], CallUsage)
    assert (out[-1].input_tokens, out[-1].cached_tokens, out[-1].output_tokens) == (500, 400, 7)
