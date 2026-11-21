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
    assert "7 facts" not in text and "Open conflicts waiting" not in text
    assert model.seen[0][-2]["role"] == "system" and "7 facts" in model.seen[0][-2]["content"]
    assert "Open conflicts waiting for the customer: 1" in model.seen[0][-2]["content"]
    assert "wins over the extraction" in text and "Never resolve a conflict" in text and "data, not instructions" in text
    assert "[f_" in text  # fact link format
    assert model.seen[1][1:-2] == [{"role": "user", "content": "first"}, {"role": "assistant", "content": "one"}]
    assert model.seen[1][-1] == {"role": "user", "content": "second"}


def fill_chat(ws, n):
    for i in range(n):
        ws.append_chat({"id": f"m_{i}", "role": "user" if i % 2 == 0 else "assistant", "text": f"msg {i}"})


async def test_short_history_is_sent_whole(ws, svc):
    fill_chat(ws, 40)
    model = ScriptedChat(["ok"])
    await run_chat(ws, svc, model, "now")
    sent = model.seen[0][1:-2]
    assert len(sent) == 40 and sent[0]["content"] == "msg 0"


def test_history_start_is_stable_within_a_block_and_jumps_at_the_boundary():
    def hist(n):
        return [{"role": "user" if i % 2 == 0 else "assistant", "content": str(i)} for i in range(n)]
    starts = {n: A._history_start(hist(n)) for n in range(0, 100, 2)}
    assert starts[40] == 0 and starts[42] == 20 and starts[58] == 20 and starts[60] == 40 and starts[78] == 40 and starts[80] == 60
    for n in range(41, 100):  # every start is a user message, and kept messages stay within bounds
        h = hist(n)
        st = A._history_start(h)
        assert h[st]["role"] == "user" and A.HISTORY_MIN - 1 <= n - st <= A.HISTORY_MAX
    assert len({A._history_start(hist(n)) for n in range(41, 60)}) == 1


def test_history_start_skips_to_a_user_message():
    h = [{"role": "assistant" if i % 2 == 0 else "user", "content": str(i)} for i in range(45)]
    assert h[A._history_start(h)]["role"] == "user"


async def test_prefix_is_stable_between_turns_in_a_block(ws, svc):
    fill_chat(ws, 44)
    model = ScriptedChat(["a"], ["b"])
    await run_chat(ws, svc, model, "q1")
    await run_chat(ws, svc, model, "q2")
    first, second = model.seen
    assert second[:-2][: len(first) - 2] == first[:-2]  # all but the state and the new question carry over
    assert second[len(first) - 2:-2] == [{"role": "user", "content": "q1"}, {"role": "assistant", "content": "a"}]
    assert first[1]["content"] == second[1]["content"] == "msg 20"


async def test_system_prompt_is_static_and_state_message_follows_edits(ws, svc):
    before_prompt, before_state = A.system_prompt(ws), A.state_message(ws)
    ws.add({"category": "D", "text": "A new deadline"}, source="chat")
    assert A.system_prompt(ws) == before_prompt
    assert A.state_message(ws) != before_state and "8 facts" in A.state_message(ws)
    assert "2026" not in before_prompt


async def test_cache_key_is_passed_only_to_models_that_take_it(ws, svc):
    got = {}

    class Keyed:
        async def stream(self, messages, tools, cache_key=None):
            got["key"] = cache_key
            yield "ok"

    await run_chat(ws, svc, Keyed())
    assert got["key"].startswith("fxchat-")
    assert A._cache_key(ws) == got["key"]
    await run_chat(ws, svc, ScriptedChat(["fine"]))  # a model without the keyword still works


async def test_openai_model_sends_prompt_cache_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    sent = {}

    async def create(**kw):
        sent.update(kw)

        async def gen():
            return
            yield
        return gen()

    model = A.OpenAIChatModel()
    model._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    [x async for x in model.stream([{"role": "user", "content": "x"}], [], cache_key="k1")]
    assert sent["prompt_cache_key"] == "k1"


async def test_stored_tool_steps_keep_arguments_and_a_summary(ws, svc):
    long = "x" * 500
    model = ScriptedChat([call("search", "c1", query="info tech", note=long), call("get_fact", "c2", fact_id="f_nope")], ["done"])
    events = await run_chat(ws, svc, model)
    assert events[0] == {"type": "tool", "name": "search", "label": "Searched the document", "ok": True}  # stream unchanged
    steps = ws.chat()[-1]["tools"]
    assert steps[0]["args"]["query"] == "info tech" and len(steps[0]["args"]["note"]) == 303
    assert steps[0]["summary"].endswith("hits")
    assert steps[1]["ok"] is False and steps[1]["summary"].startswith("error: no fact f_nope")
    ok = [s for s in steps if s["ok"]]
    assert all(k in ok[0] for k in ("name", "label", "ok"))


async def test_old_chats_without_args_still_load(ws, svc):
    ws.append_chat({"id": "m_q", "role": "user", "text": "q"})
    ws.append_chat({"id": "m_old", "role": "assistant", "text": "hi", "tools": [{"name": "search", "label": "Searched", "ok": True}]})
    model = ScriptedChat(["ok"])
    await run_chat(ws, svc, model)
    assert ws.chat()[1]["tools"] == [{"name": "search", "label": "Searched", "ok": True}]
    assert {"role": "assistant", "content": "hi"} in model.seen[0]


@pytest.mark.parametrize("a,b", [("infotech", "Info-Tech"), ("info tech", "INFO TECH"), ("INFOTECH", "info\u2011tech"),
                                 ("email", "E-mail"), ("coop", "Co-op"), ("e-mail", "email"), ("city's", "citys"),
                                 ("bid", "bids"), ("cities", "city"), ("Info-Tech", "info tech")])
def test_token_variants_match(a, b):
    assert A._score(A._tokens(a), b) >= 1 and A._score(A._tokens(b), a) >= 1


def test_tokens_do_not_over_match():
    assert not A._tokens("class") & A._tokens("clas")
    assert not A._tokens("info") & A._tokens("tech")


async def test_search_ranks_more_distinct_terms_over_one_common_word(ws, svc):
    facts = [{"category": "B", "text": f"Info about item {i} is on the portal"} for i in range(6)]
    facts.append({"category": "B", "text": "The City engaged Info-Tech Research Group to select the partner"})
    ids = [ws.add(f, source="chat")["fact_id"] for f in facts]
    ctx = A.Ctx(ws, svc, [])
    for q in ("infotech select", "info tech select", "INFO-TECH SELECT"):
        assert (await A.t_search(ctx, {"query": q}))["hits"][0]["fact_id"] == ids[-1]
    assert (await A.t_search(ctx, {"query": "why are we messaging infotech?"}))["hits"][0]["fact_id"] == ids[-1]


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
    assert events[-1]["message"]["tools"] == [{"name": "edit_fact", "label": "Changed fact f_d1", "ok": True, "summary": "f_d1",
                                               "args": {"fact_id": "f_d1", "text": "Bids due March 5", "reason": "customer said 5 March"}}]
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
    model = ScriptedChat(*[[call("search", query="bids")] for _ in range(20)])
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
    r = await A.t_search(ctx, {"query": "March 5 bids"})
    assert r["hits"][0]["fact_id"] == "f_d2" and r["count"] >= 2
    assert (await A.t_search(ctx, {"query": "nothing matches zzz"}))["hits"] == []
    by_cat = await A.t_search(ctx, {"category": "D", "limit": 2})
    assert [f["fact_id"] for f in by_cat["hits"]] == ["f_d1", "f_d3"] and by_cat["count"] == 3
    assert [f["fact_id"] for f in (await A.t_search(ctx, {"flag": "mandatory"}))["hits"]] == ["f_d1"]
    assert [f["fact_id"] for f in (await A.t_search(ctx, {"status": "conflict"}))["hits"]] == ["f_d1"]
    ws.edit("f_b1", {"note": "n"})
    assert [f["fact_id"] for f in (await A.t_search(ctx, {"edited": True}))["hits"]] == ["f_b1"]
    cited = await A.t_search(ctx, {"query": "shall give support"})  # words of the cited text count
    assert cited["hits"][0]["fact_id"] == "f_r1"


async def test_get_fact(ws, svc):
    ctx = A.Ctx(ws, svc, [])
    ws.edit("f_d1", {"text": "changed"})
    f = await A.t_get_fact(ctx, {"fact_id": "f_d1"})
    assert f["original"] == {"text": "Bids due March 3"} and f["citations"][0]["text"] == "Bids are due March 3."
    assert "bbox" not in f["citations"][0]
    with pytest.raises(Exception, match="no fact"):
        await A.t_get_fact(ctx, {"fact_id": "zz"})


async def test_conflict_and_summary_tools(ws, svc):
    ctx = A.Ctx(ws, svc, [])
    cs = await A.t_list_conflicts(ctx, {"status": "open"})
    assert cs["conflicts"][0]["conflict_id"] == "q:f_q1" and cs["conflicts"][0]["options"][1]["index"] == 1
    r = await A.t_resolve_conflict(ctx, {"conflict_id": "q:f_q1", "option": 1})
    assert r["resolution"]["option"] == 1
    assert (await A.t_list_conflicts(ctx, {"status": "open"}))["conflicts"] == []
    started = await A.t_generate_summary(ctx, {"sections": ["submission"]})
    assert started["started"] == ["submission"]
    await svc.wait_idle()
    got = await A.t_get_summary(ctx, {"section": "submission"})
    s0 = got["sections"][0]
    assert s0["key"] == "submission" and s0["rows"][0]["row"] == "Deadline" and s0["rows"][0]["fact_ids"] and s0["stale"] is False
    assert set(s0["rows"][0]) == {"row", "text", "fact_ids"}
    assert (await A.t_facts_not_in_summary(ctx, {"section": "submission"}))["sections"]["submission"]["has_rows"] is True
    assert (await A.t_facts_not_in_summary(ctx, {"section": "contract"}))["sections"]["contract"]["has_rows"] is False
    with pytest.raises(Exception, match="unknown section"):
        await A.t_get_summary(ctx, {"section": "nope"})
    assert "pin" not in A.SYSTEM_PROMPT.lower()


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
    assert names == ["search", "get_fact", "edit_fact", "delete_fact", "add_fact", "restore_fact",
                     "list_conflicts", "raise_conflict", "resolve_conflict", "get_summary", "facts_not_in_summary",
                     "generate_summary"]
    json.dumps(A.TOOL_SPECS)


async def test_openai_model_assembles_streamed_tool_call_deltas(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")

    def chunk(content=None, tool_calls=None):
        return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=content, tool_calls=tool_calls))])

    def tc(index, id=None, name=None, args=None):
        return SimpleNamespace(index=index, id=id, function=SimpleNamespace(name=name, arguments=args))

    async def gen():
        for c in (chunk("Hel"), chunk("lo"), chunk(tool_calls=[tc(0, "call_a", "get_fact", '{"fact_')]),
                  chunk(tool_calls=[tc(0, None, None, 'id": "f_1"}'), tc(1, "call_b", "search", "{}")]),
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
    assert out[2:] == [A.ToolCall("call_a", "get_fact", '{"fact_id": "f_1"}'), A.ToolCall("call_b", "search", "{}")]
    assert sent["stream"] is True and sent["tools"] is A.TOOL_SPECS and "temperature" not in sent
    assert "max_completion_tokens" in sent and "reasoning_effort" in sent


def test_model_unavailable_is_an_exception_with_a_message():
    assert str(ModelUnavailable("x")) == "x"


async def test_last_round_has_no_tools_so_the_model_answers(ws, svc):
    class Greedy(ScriptedChat):
        async def stream(self, messages, tools):
            self.seen.append(json.loads(json.dumps(messages)))
            self.tools = getattr(self, "tools", []) + [bool(tools)]
            for item in ([call("search", query="bids")] if tools else ["Here is what I found."]):
                yield item

    model = Greedy()
    events = await run_chat(ws, svc, model)
    assert model.tools == [True] * A.MAX_ROUNDS + [False]
    assert types(events)[-1] == "done" and "error" not in types(events)
    assert events[-1]["message"]["text"] == "Here is what I found."


async def test_search_covers_the_labelled_text_of_the_document(ws, svc):
    (ws.facts_path.parent / "labels.json").write_text(json.dumps([
        {"id": "p9.1", "page": "9", "text": "Living wage applies to staff.", "label": "-", "flags": [], "votes": ["-", "-", "S"]},
        {"id": "p2.1", "page": "2", "text": "Bids are due March 3.", "label": "D", "flags": [], "votes": ["D", "D", "D"]}]), encoding="utf-8")
    ctx = A.Ctx(ws, svc, [])
    hit = (await A.t_search(ctx, {"query": "living wage"}))["hits"]
    assert [(h["unit_id"], h["label"], h["votes"]) for h in hit] == [("p9.1", "-", ["-", "-", "S"])]  # a dropped unit is found
    assert "fact_id" not in hit[0]
    only = (await A.t_search(ctx, {"query": "due wage", "label": "-"}))["hits"]
    assert [h["unit_id"] for h in only] == ["p9.1"]
    no_unit = (await A.t_search(ctx, {"label": "-", "category": "D"}))["hits"]
    assert no_unit == []  # a fact filter needs a fact
    res = await A.t_search(ctx, {"query": "zzz"})
    assert res["hits"] == [] and "note" not in res


async def test_one_search_call_can_carry_several_queries(ws, svc):
    one = await A.t_search(A.Ctx(ws, svc, []), {"query": "March 5 bids"})
    ctx = A.Ctx(ws, svc, [])
    many = await A.t_search(ctx, {"queries": ["March 5 bids", "bids March", "zzz nothing"]})
    first, second, none = many["results"]
    assert first["query"] == "March 5 bids" and first["hits"] == one["hits"][: A.MULTI_QUERY_LIMIT]
    shown = {h["fact_id"] for h in first["hits"]}
    repeats = [h for h in second["hits"] if h.get("fact_id") in shown]
    assert repeats and all(h == {"fact_id": h["fact_id"], "sent_before": True} for h in repeats)  # in full only once
    assert none == {"query": "zzz nothing", "count": 0, "hits": []}
    filtered = await A.t_search(A.Ctx(ws, svc, []), {"queries": ["bids", "questions"], "category": "D"})
    assert all(h.get("fact_id", "").startswith("f_d") for r in filtered["results"] for h in r["hits"])
    for bad in ([], "bids", [1]):
        with pytest.raises(A.WorkspaceError):
            await A.t_search(ctx, {"queries": bad})
    assert A._summary(many).startswith("March 5 bids: ")


async def test_no_tool_calls_keep_the_tool_list_for_models_that_can_refuse_tools(ws, svc):
    class Refusing(ScriptedChat):
        async def stream(self, messages, tools, allow_tools=True):
            self.calls = getattr(self, "calls", []) + [(len(tools), allow_tools)]
            for item in ([call("search", query="bids")] if allow_tools else ["Answer."]):
                yield item

    model = Refusing()
    await run_chat(ws, svc, model)
    n = len(A.TOOL_SPECS)
    assert model.calls == [(n, True)] * A.MAX_ROUNDS + [(n, False)]  # same tools on the last call, refused


async def test_openai_model_sends_tool_choice_none_when_tools_are_refused(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    sent = []

    async def create(**kw):
        sent.append(kw)

        async def gen():
            return
            yield
        return gen()

    model = A.OpenAIChatModel()
    model._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    msgs = [{"role": "user", "content": "x"}]
    [x async for x in model.stream(msgs, A.TOOL_SPECS, allow_tools=False)]
    [x async for x in model.stream(msgs, A.TOOL_SPECS)]
    [x async for x in model.stream(msgs, [], allow_tools=False)]
    assert sent[0]["tools"] == A.TOOL_SPECS and sent[0]["tool_choice"] == "none"
    assert "tool_choice" not in sent[1] and "tools" not in sent[2] and "tool_choice" not in sent[2]


async def test_several_queries_cap_hits_per_query(ws, svc, monkeypatch):
    monkeypatch.setattr(A, "MULTI_QUERY_LIMIT", 2)
    ctx = A.Ctx(ws, svc, [])
    r = await A.t_search(ctx, {"queries": ["bids", "March"], "limit": 100})
    assert all(len(x["hits"]) <= 2 for x in r["results"])
    assert len((await A.t_search(ctx, {"query": "bids March questions", "limit": 100}))["hits"]) > 2  # one query: as before


async def test_search_rows_are_slim(ws, svc):
    (ws.facts_path.parent / "labels.json").write_text(json.dumps([
        {"id": "p2.1", "page": "2", "text": "Bids are due March 3.", "label": "D", "flags": [], "votes": ["D", "D", "D"]},
        {"id": "p9.1", "page": "9", "text": "Living wage " + "x " * 400, "label": "-", "flags": [], "votes": ["-", "-", "S"]}]),
        encoding="utf-8")
    ctx = A.Ctx(ws, svc, [])
    fact_row = next(h for h in (await A.t_search(ctx, {"query": "bids due March"}))["hits"] if h.get("fact_id") == "f_d1")
    # the fact line only: no source text, no default status, no unanimous votes, no edited/deleted
    assert set(fact_row) <= {"fact_id", "category", "text", "page", "section", "flags", "status"}
    assert "unit_text" not in fact_row and "votes" not in fact_row and "edited" not in fact_row
    unit_row = (await A.t_search(A.Ctx(ws, svc, []), {"query": "living wage"}))["hits"][0]
    assert unit_row["votes"] == ["-", "-", "S"]  # split votes are kept
    assert len(unit_row["unit_text"]) == A.UNIT_TEXT_CHARS + 3 and unit_row["unit_text"].endswith("...")
    ws.edit("f_d1", {"note": "n"})
    edited = next(h for h in (await A.t_search(A.Ctx(ws, svc, []), {"query": "bids due"}))["hits"] if h.get("fact_id") == "f_d1")
    assert edited["edited"] is True


async def test_rows_sent_earlier_in_a_turn_come_back_as_ids(ws, svc):
    ctx = A.Ctx(ws, svc, [])
    first = (await A.t_search(ctx, {"query": "bids due"}))["hits"]
    again = (await A.t_search(ctx, {"queries": ["bids due"], "category": "D"}))["results"][0]["hits"]
    assert first and all(h == {"fact_id": h["fact_id"], "sent_before": True} for h in again if h.get("fact_id") in {x.get("fact_id") for x in first})
    fresh = (await A.t_search(A.Ctx(ws, svc, []), {"query": "bids due"}))["hits"]  # a new turn starts clean
    assert fresh == first


async def test_rare_words_outrank_common_ones_and_the_weak_tail_is_cut(ws, svc):
    for i in range(12):
        ws.add({"category": "B", "text": f"The City of Springfield will review item {i}."}, source="chat")
    target = ws.add({"category": "C", "text": "The contractor must carry insurance."}, source="chat")["fact_id"]
    ctx = A.Ctx(ws, svc, [])
    hits = (await A.t_search(ctx, {"query": "City of Springfield insurance", "limit": 50}))["hits"]
    assert hits[0]["fact_id"] == target  # one rare word beats several common ones
    r = await A.t_search(A.Ctx(ws, svc, []), {"query": "contractor insurance review", "limit": 50})
    assert r["hits"][0]["fact_id"] == target
    # the 12 rows that share only the common word "review" score far below the best match: left out
    assert [h["fact_id"] for h in r["hits"]] == [target] and r["count"] == 1


async def test_search_defaults(ws, svc):
    assert (A.SEARCH_LIMIT, A.MULTI_QUERY_LIMIT) == (10, 6)
    for i in range(30):
        ws.add({"category": "B", "text": f"Bids note {i}"}, source="chat")
    assert len((await A.t_search(A.Ctx(ws, svc, []), {"query": "bids note"}))["hits"]) == A.SEARCH_LIMIT
    assert len((await A.t_search(A.Ctx(ws, svc, []), {"query": "bids note", "limit": 25}))["hits"]) == 25


async def test_section_headings_are_searched_and_filter(ws, svc):
    (ws.facts_path.parent / "labels.json").write_text(json.dumps([
        {"id": "u40.1", "page": "40", "section": "5.2 Insurance", "text": "General liability of at least $1,000,000.", "label": "C", "flags": [], "votes": ["C"] * 3},
        {"id": "u40.2", "page": "40", "section": "5.2 Insurance", "text": "Auto liability of at least $500,000.", "label": "C", "flags": [], "votes": ["C"] * 3},
        {"id": "u50.1", "page": "50", "section": "6 Pricing", "text": "Prices stay valid for 90 days.", "label": "C", "flags": [], "votes": ["C"] * 3}]),
        encoding="utf-8")
    hits = (await A.t_search(A.Ctx(ws, svc, []), {"query": "insurance"}))["hits"]
    # neither sentence says "insurance"; their section heading does
    assert {h["unit_id"] for h in hits} == {"u40.1", "u40.2"} and all(h["section"] == "5.2 Insurance" for h in hits)
    sec = (await A.t_search(A.Ctx(ws, svc, []), {"section": "insurance"}))["hits"]
    assert [h["unit_id"] for h in sec] == ["u40.1", "u40.2"]
    r = await A.t_search(A.Ctx(ws, svc, []), {"queries": ["liability"], "limit": 1})
    assert r["results"][0]["count"] == 2 and r["results"][0]["more"] == 1  # more: matched but not shown


async def test_get_fact_reads_several_and_leaves_out_empty_fields(ws, svc):
    ctx = A.Ctx(ws, svc, [])
    one = await A.t_get_fact(ctx, {"fact_id": "f_d1"})
    assert "problems" not in one and "deleted" not in one and one["citations"]
    many = await A.t_get_fact(ctx, {"fact_ids": ["f_d1", "f_d2", "f_d1", "nope"]})
    assert [f["fact_id"] for f in many["facts"]] == ["f_d1", "f_d2"] and many["not_found"] == ["nope"]
    assert A._summary(many) == "f_d1, f_d2; not found: ['nope']"
    with pytest.raises(A.WorkspaceError):
        await A.t_get_fact(ctx, {"fact_ids": []})
    events = await run_chat(ws, svc, ScriptedChat([call("get_fact", fact_ids=["f_d1", "f_d2"]), call("get_fact", "c2", fact_id="f_d1")], ["ok"]))
    assert [e["label"] for e in events if e["type"] == "tool"] == ["Read 2 facts", "Read fact f_d1"]
