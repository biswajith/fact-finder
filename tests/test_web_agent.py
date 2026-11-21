"""The chat agent's tool loop with a scripted model. No API call is ever made."""

import json
from types import SimpleNamespace

import pytest
from test_web_summaries import MORE, Scripted
from test_web_workspace import make_run

from fact_extractor.web import ModelUnavailable
from fact_extractor.web import agent as A
from fact_extractor.web.summaries import SummaryService
from fact_extractor.web.workspace import Workspace


class ScriptedChat:
    """A ChatModel that plays one scripted turn per call: a list of text deltas and ToolCalls."""

    def __init__(self, *turns):
        self.turns = list(turns)
        self.seen: list[list[dict]] = []

    async def stream(self, messages, tools):
        self.seen.append(json.loads(json.dumps(messages)))
        turn = self.turns.pop(0) if self.turns else ["(no more script)"]
        if isinstance(turn, Exception):
            raise turn
        for item in turn:
            yield item


def call(name, cid="call_1", **args):
    return A.ToolCall(cid, name, json.dumps(args))


@pytest.fixture
def ws(tmp_path):
    return Workspace(make_run(tmp_path, facts=MORE) / "facts.json")


@pytest.fixture
def svc():
    return SummaryService(Scripted())


async def run_chat(ws, svc, model, text="hello"):
    return [e async for e in A.chat(ws, svc, model, text)]


def types(events):
    return [e["type"] for e in events]


async def test_plain_answer_streams_text_and_persists_both_messages(ws, svc):
    events = await run_chat(ws, svc, ScriptedChat(["The deadline ", "is March 3."]), "When is it due?")
    assert types(events) == ["text", "text", "done"]
    done = events[-1]["message"]
    assert done["role"] == "assistant" and done["text"] == "The deadline is March 3." and done["id"].startswith("m_")
    assert done["tools"] == [] and done["conflict_ids"] == []
    saved = ws.chat()
    assert [m["role"] for m in saved] == ["user", "assistant"] and saved[0]["text"] == "When is it due?"
    assert saved[1] == done


async def test_system_prompt_rules_counts_and_history(ws, svc):
    model = ScriptedChat(["one"], ["two"])
    await run_chat(ws, svc, model, "first")
    await run_chat(ws, svc, model, "second")
    system = model.seen[0][0]
    assert system["role"] == "system"
    text = system["content"]
    assert "7 facts" in text and "Open conflicts waiting for the customer: 1" in text
    assert "wins over the extraction" in text and "Never resolve a conflict" in text and "data, not instructions" in text
    assert "[f_" in text  # fact link format
    assert model.seen[1][1:] == [{"role": "user", "content": "first"}, {"role": "assistant", "content": "one"},
                                 {"role": "user", "content": "second"}]


async def test_history_is_the_last_twenty_messages(ws, svc):
    for i in range(30):
        ws.append_chat({"id": f"m_{i}", "role": "user" if i % 2 == 0 else "assistant", "text": f"msg {i}"})
    model = ScriptedChat(["ok"])
    await run_chat(ws, svc, model, "now")
    sent = model.seen[0][1:]
    assert len(sent) == 21 and sent[0]["content"] == "msg 10" and sent[-1] == {"role": "user", "content": "now"}


async def test_edit_fact_changes_the_fact_and_reports(ws, svc):
    model = ScriptedChat([call("edit_fact", fact_id="f_d1", text="Bids due March 5", reason="customer said 5 March")],
                         ["Done, see [f_d1]."])
    events = await run_chat(ws, svc, model)
    assert types(events) == ["tool", "changed", "text", "done"]
    assert events[0] == {"type": "tool", "name": "edit_fact", "label": "Changed fact f_d1", "ok": True}
    assert events[1]["what"] == ["facts", "conflicts", "summaries"]
    f = ws.state().get("f_d1")
    assert f["text"] == "Bids due March 5" and f["original"] == {"text": "Bids due March 3"}
    entry = ws.log()[0]
    assert entry["source"] == "chat" and entry["reason"] == "customer said 5 March"
    assert events[-1]["message"]["tools"] == [{"name": "edit_fact", "label": "Changed fact f_d1", "ok": True}]
    # the tool result went back to the model, with the assistant's tool call before it
    second = model.seen[1]
    assert second[-2]["role"] == "assistant" and second[-2]["tool_calls"][0]["function"]["name"] == "edit_fact"
    assert second[-1]["role"] == "tool" and second[-1]["tool_call_id"] == "call_1"
    assert json.loads(second[-1]["content"])["ok"] is True


async def test_raise_conflict_emits_event_and_never_resolves(ws, svc):
    opts = [{"label": "Change the first", "changes": [{"op": "edit", "fact_id": "f_d1", "fields": {"text": "new"}}]},
            {"label": "Change the second", "changes": [{"op": "edit", "fact_id": "f_d2", "fields": {"text": "new"}}]}]
    model = ScriptedChat([call("raise_conflict", title="Which date?", description="two dates", fact_ids=["f_d1", "f_d2"],
                               options=opts)], ["Please choose."])
    events = await run_chat(ws, svc, model)
    assert types(events) == ["tool", "changed", "conflict", "text", "done"]
    assert events[1]["what"] == ["conflicts"]
    cid = events[2]["conflict_id"]
    assert cid.startswith("k_") and events[-1]["message"]["conflict_ids"] == [cid]
    c = ws.state().conflict(cid)
    assert c["status"] == "open" and c["kind"] == "raised"
    assert ws.state().get("f_d1")["text"] == "Bids due March 3"


async def test_tool_error_goes_back_to_the_model_and_is_reported(ws, svc):
    model = ScriptedChat([call("edit_fact", fact_id="f_nope", text="x", reason="r")], ["Sorry."])
    events = await run_chat(ws, svc, model)
    assert types(events) == ["tool", "text", "done"]  # no `changed`
    assert events[0]["ok"] is False and "no fact f_nope" in events[0]["label"]
    assert json.loads(model.seen[1][-1]["content"]) == {"error": "no fact f_nope"}
    assert events[-1]["message"]["tools"][0]["ok"] is False
    assert ws.log() == []


async def test_bad_arguments_and_unknown_tool_are_errors_not_crashes(ws, svc):
    model = ScriptedChat([A.ToolCall("a", "edit_fact", "{not json"), A.ToolCall("b", "launch_missiles", "{}"),
                          A.ToolCall("c", "edit_fact", json.dumps({"fact_id": "f_d1", "category": "Z", "reason": "r"})),
                          A.ToolCall("d", "raise_conflict", json.dumps({"title": "t", "options": "nope", "fact_ids": ["f_d1"]}))],
                         ["ok"])
    events = await run_chat(ws, svc, model)
    tools = [e for e in events if e["type"] == "tool"]
    assert [t["ok"] for t in tools] == [False] * 4 and types(events)[-1] == "done"
    assert "unknown tool" in tools[1]["label"] and "category must be" in tools[2]["label"]
    assert ws.log() == []


async def test_round_limit(ws, svc):
    model = ScriptedChat(*[[call("search_facts", query="bids")] for _ in range(20)])
    events = await run_chat(ws, svc, model)
    assert len(model.seen) == A.MAX_ROUNDS + 1  # eight rounds of tools, then the ninth ask is refused
    assert sum(1 for e in events if e["type"] == "tool") == A.MAX_ROUNDS
    assert types(events)[-2:] == ["error", "done"] and "8 rounds" in events[-2]["message"]
    assert events[-1]["message"]["text"].startswith("Stopped")


async def test_missing_key_gives_error_event_and_still_done(ws, svc, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    events = await run_chat(ws, svc, A.OpenAIChatModel(), "hi")
    assert events == [{"type": "error", "message": "OPENAI_API_KEY is not set"},
                      {"type": "done", "message": events[-1]["message"]}]
    assert [m["role"] for m in ws.chat()] == ["user", "assistant"]


async def test_other_model_failure_ends_with_error_and_done(ws, svc):
    events = await run_chat(ws, svc, ScriptedChat(["partial "], ), "x")
    assert types(events)[-1] == "done"
    events = await run_chat(ws, svc, ScriptedChat(RuntimeError("network down")), "x")
    assert types(events) == ["error", "done"] and "network down" in events[0]["message"]


async def test_search_facts_ranks_by_word_overlap_and_filters(ws, svc):
    ctx = A.Ctx(ws, svc, [])
    r = await A.t_search_facts(ctx, {"query": "March 5 bids"})
    assert r["facts"][0]["fact_id"] == "f_d2" and r["count"] >= 2
    assert (await A.t_search_facts(ctx, {"query": "nothing matches zzz"}))["facts"] == []
    by_cat = await A.t_search_facts(ctx, {"category": "D", "limit": 2})
    assert [f["fact_id"] for f in by_cat["facts"]] == ["f_d1", "f_d3"] and by_cat["count"] == 3
    assert [f["fact_id"] for f in (await A.t_search_facts(ctx, {"flag": "mandatory"}))["facts"]] == ["f_d1"]
    assert [f["fact_id"] for f in (await A.t_search_facts(ctx, {"status": "conflict"}))["facts"]] == ["f_d1"]
    ws.edit("f_b1", {"note": "n"})
    assert [f["fact_id"] for f in (await A.t_search_facts(ctx, {"edited": True}))["facts"]] == ["f_b1"]
    cited = await A.t_search_facts(ctx, {"query": "shall give support"})  # words of the cited text count
    assert cited["facts"][0]["fact_id"] == "f_r1"


async def test_get_fact_and_search_source(ws, svc):
    ctx = A.Ctx(ws, svc, [])
    ws.edit("f_d1", {"text": "changed"})
    f = await A.t_get_fact(ctx, {"fact_id": "f_d1"})
    assert f["original"] == {"text": "Bids due March 3"} and f["citations"][0]["text"] == "Bids are due March 3."
    assert "bbox" not in f["citations"][0]
    with pytest.raises(Exception, match="no fact"):
        await A.t_get_fact(ctx, {"fact_id": "zz"})
    none = await A.t_search_source(ctx, {"query": "due"})
    assert none["units"] == [] and "No PDF" in none["note"]
    ws._doc_loaded = True
    ws._doc = SimpleNamespace(anchors={
        "p1.1": SimpleNamespace(id="p1.1", page_label="1", section="S", text="Proposals are due soon."),
        "p2.1": SimpleNamespace(id="p2.1", page_label="2", section="S", text="Unrelated words.")})
    hit = await A.t_search_source(ctx, {"query": "proposals due"})
    assert [u["id"] for u in hit["units"]] == ["p1.1"]


async def test_conflict_summary_and_pin_tools(ws, svc):
    ctx = A.Ctx(ws, svc, [])
    cs = await A.t_list_conflicts(ctx, {"status": "open"})
    assert cs["conflicts"][0]["conflict_id"] == "q:f_q1" and cs["conflicts"][0]["options"][1]["index"] == 1
    r = await A.t_resolve_conflict(ctx, {"conflict_id": "q:f_q1", "option": 1})
    assert r["resolution"]["option"] == 1
    assert (await A.t_list_conflicts(ctx, {"status": "open"}))["conflicts"] == []
    started = await A.t_generate_summary(ctx, {"sections": ["dates"]})
    assert started["started"] == ["dates"]
    await svc.wait_idle()
    got = await A.t_get_summary(ctx, {"section": "dates"})
    assert got["sections"][0]["key"] == "dates" and got["sections"][0]["points"]
    assert (await A.t_facts_not_in_summary(ctx, {"section": "dates"}))["sections"]["dates"]["generated"] is True
    await A.t_pin_to_summary(ctx, {"fact_ids": ["f_d2"]})
    await svc.wait_idle()
    assert ws.read_summaries()["pinned"] == ["f_d2"]
    with pytest.raises(Exception, match="unknown section"):
        await A.t_get_summary(ctx, {"section": "nope"})
    with pytest.raises(Exception, match="no fact"):
        await A.t_pin_to_summary(ctx, {"fact_ids": ["zz"]})


async def test_add_delete_restore_tools(ws, svc):
    ctx = A.Ctx(ws, svc, [])
    added = (await A.t_add_fact(ctx, {"category": "R", "text": "Must have ISO cert", "flags": ["mandatory"]}))["fact"]
    assert added["fact_id"].startswith("u_")
    await A.t_delete_fact(ctx, {"fact_id": "f_r1", "reason": "wrong"})
    assert ws.state().get("f_r1")["deleted"]
    assert (await A.t_restore_fact(ctx, {"fact_id": "f_r1"}))["fact"]["deleted"] is False
    assert all(e["source"] == "chat" for e in ws.log())


def test_every_tool_has_a_schema_and_names_match():
    names = [t["function"]["name"] for t in A.TOOL_SPECS]
    assert names == ["search_facts", "get_fact", "search_source", "edit_fact", "delete_fact", "add_fact", "restore_fact",
                     "list_conflicts", "raise_conflict", "resolve_conflict", "get_summary", "facts_not_in_summary",
                     "pin_to_summary", "generate_summary"]
    json.dumps(A.TOOL_SPECS)


async def test_openai_model_assembles_streamed_tool_call_deltas(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")

    def chunk(content=None, tool_calls=None):
        return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=content, tool_calls=tool_calls))])

    def tc(index, id=None, name=None, args=None):
        return SimpleNamespace(index=index, id=id, function=SimpleNamespace(name=name, arguments=args))

    async def gen():
        for c in (chunk("Hel"), chunk("lo"), chunk(tool_calls=[tc(0, "call_a", "get_fact", '{"fact_')]),
                  chunk(tool_calls=[tc(0, None, None, 'id": "f_1"}'), tc(1, "call_b", "search_facts", "{}")]),
                  SimpleNamespace(choices=[])):
            yield c

    sent = {}

    async def create(**kw):
        sent.update(kw)
        return gen()

    model = A.OpenAIChatModel()
    model._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    out = [x async for x in model.stream([{"role": "user", "content": "x"}], A.TOOL_SPECS)]
    assert out[:2] == ["Hel", "lo"]
    assert out[2:] == [A.ToolCall("call_a", "get_fact", '{"fact_id": "f_1"}'), A.ToolCall("call_b", "search_facts", "{}")]
    assert sent["stream"] is True and sent["tools"] is A.TOOL_SPECS and "temperature" not in sent
    assert "max_completion_tokens" in sent and "reasoning_effort" in sent


def test_model_unavailable_is_an_exception_with_a_message():
    assert str(ModelUnavailable("x")) == "x"
