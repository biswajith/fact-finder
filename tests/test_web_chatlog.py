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


def test_cost_estimates_use_the_price_table():
    from fact_extractor.web import pricing

    # 200K input with 80K cached, 20K output: 120K x $0.10 + 80K x $0.01 + 20K x $0.50 per 1M
    assert pricing.cost(pricing.CHAT, "gpt-6-luna", 200_000, 80_000, 20_000) == pytest.approx(0.012 + 0.0008 + 0.01)
    # over 272K input: 2x input and cache rates, 1.5x output
    assert pricing.cost(pricing.CHAT, "gpt-6-luna", 300_000, 0, 1_000) == pytest.approx((300_000 * 0.2 + 1_000 * 0.75) / 1e6)
    assert pricing.cost(pricing.DECISIONS, "gpt-6-luna", 1_000_000) == pytest.approx(0.10)
    assert pricing.cost(pricing.CHAT, "unknown-model", 1000) is None
    assert pricing.cost(pricing.CHAT, "gpt-6-luna", None) is None


async def test_turns_log_estimated_cost(ws, svc):
    class Counted(ScriptedChat):
        async def stream(self, messages, tools):
            async for item in super().stream(messages, tools):
                yield item
            yield CallUsage(10_000, 8_000, 500, "gpt-6-luna")

    fake = FakeDecisions(choice("direct"))
    await run(ws, svc, Counted(["Hi."]), P.Planning(P.DecisionsRouter(client=fake)))
    log = ws.chat_events(ws.chat_session())
    call = next(e for e in log if e["event"] == "llm_call")
    llm = (2_000 * 0.10 + 8_000 * 0.01 + 500 * 0.50) / 1e6
    assert call["cost_usd"] == pytest.approx(llm)
    route = next(e for e in log if e["event"] == "route")
    dec = 10 * 0.10 / 1e6  # FakeDecisions reports 10 input tokens
    assert route["call"]["cost_usd"] == pytest.approx(dec)
    totals = log[-1]["totals"]
    assert totals["llm_cost_usd"] == pytest.approx(llm) and totals["decisions_cost_usd"] == pytest.approx(dec)
    assert totals["cost_usd"] == pytest.approx(llm + dec)
    assert ws.chat_sessions()[0]["totals"]["cost_usd"] == pytest.approx(llm + dec)


def test_events_logged_before_costs_are_priced_when_read():
    from fact_extractor.web.pricing import fill_costs

    old = [
        {"turn_id": "t1", "event": "route", "call": {"model": "gpt-6-luna", "input_tokens": 400}},
        {"turn_id": "t1", "event": "llm_call", "model": "gpt-6-luna", "input_tokens": 2000, "cached_tokens": 1000, "output_tokens": 100},
        {"turn_id": "t1", "event": "turn_end", "totals": {"llm_calls": 1}},
        {"turn_id": "t2", "event": "llm_call", "model": "gpt-6-luna", "input_tokens": 10, "cost_usd": 0.5},  # kept as logged
        {"turn_id": "t2", "event": "turn_end", "totals": {"cost_usd": 0.5}},
        {"turn_id": "t3", "event": "llm_call", "input_tokens": 10},  # no model: not priced
        {"turn_id": "t3", "event": "turn_end", "totals": {}},
    ]
    filled = fill_costs(old)
    llm = (1000 * 0.10 + 1000 * 0.01 + 100 * 0.50) / 1e6
    assert filled[1]["cost_usd"] == pytest.approx(llm)
    assert filled[0]["call"]["cost_usd"] == pytest.approx(400 * 0.10 / 1e6)
    assert filled[2]["totals"]["cost_usd"] == pytest.approx(llm + 4e-5) and filled[2]["cost_added_later"]
    assert filled[4]["totals"] == {"cost_usd": 0.5} and "cost_added_later" not in filled[4]
    assert "cost_usd" not in filled[5] and "cost_usd" not in filled[6]["totals"]
    assert "cost_usd" not in old[1]  # the input is not changed


async def test_deleting_sessions(ws, svc):
    await run(ws, svc, ScriptedChat(["one"]))
    old = ws.chat_session()
    ws.clear_chat()
    await run(ws, svc, ScriptedChat(["two"]))
    cur = ws.chat_session()
    # an old session: only its log goes; the chat stays
    assert ws.delete_chat_session(old) == {"ok": True, "deleted": [old], "chat_cleared": False}
    assert [s["session_id"] for s in ws.chat_sessions()] == [cur] and len(ws.chat()) == 2
    with pytest.raises(NotFound):
        ws.chat_events(old)
    # the current session: the chat is cleared too, and the next message starts a new session
    assert ws.delete_chat_session(cur)["chat_cleared"] is True
    assert ws.chat() == [] and ws.chat_sessions() == []
    await run(ws, svc, ScriptedChat(["three"]))
    assert ws.chat_session() not in (old, cur)
    with pytest.raises(NotFound):
        ws.delete_chat_session("../../facts")
    r = ws.delete_chat_sessions()
    assert r["chat_cleared"] and len(r["deleted"]) == 1 and ws.chat_sessions() == [] and ws.chat() == []
    assert ws.facts_path.exists() and ws.delete_chat_sessions()["deleted"] == []  # facts untouched; deleting none is fine
