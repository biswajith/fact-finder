"""Speakers' sides by the model (speakers.py): the answer checked in code, and how the bid uses it."""

import asyncio

import pytest
from conftest import ScriptedClient, who_answer

from fact_extractor import bid as B
from fact_extractor import cutters, playbooks, speakers
from fact_extractor.api import SourceUnit
from fact_extractor.llm import CallFailed

HEADER = """Meeting: Kickoff
Date: 2026-03-02
Attendees:
  Ann Lee - Fenwick Advisory, Principal (the town's selection advisor)
  Bo Kim - Town of Marlow, Finance Director
  Cy Day - Northgate Systems
  Di Fox
  +1 555 010 0199 (joined by phone)

[00:00:01] Ann Lee: Welcome all. Fenwick set this call up for the town.
[00:00:09] Bo Kim: Thanks. We want to hear the plan.
[00:00:15] Cy Day: Happy to walk through it.
[00:00:20] Di Fox: Same here.
[00:00:30] +1 555 010 0199: Hello, can you hear me?
"""


def tagged(text: str = HEADER):
    from fact_extractor.api import document_from_units

    return document_from_units("call", cutters.read(text.encode(), "call.txt"))[0]


async def ainfo():
    return B.Bid.call_info({"voices": await speakers.find_voices(tagged(), ScriptedClient(who_answer))})


def info():
    return asyncio.run(ainfo())


def test_the_model_says_who_speaks_each_line_and_lines_no_one_speaks_have_no_name():
    doc = tagged()
    voices = asyncio.run(speakers.find_voices(doc, ScriptedClient(who_answer)))
    said = {doc.anchors[i].text: n for i, n in voices.items()}
    assert said["[00:00:09] Bo Kim: Thanks."] == "Bo Kim" and said["We want to hear the plan."] == "Bo Kim"
    assert "Meeting: Kickoff" not in said and "Attendees:" not in said
    assert [s["name"] for s in info()["speakers"]] == ["Ann Lee", "Bo Kim", "Cy Day", "Di Fox", "+1 555 010 0199"]


def test_who_keeps_only_asked_ids_and_names_the_document_writes():
    doc = tagged()
    ids = list(doc.anchors)
    answer = f"{ids[-1]}|Zed Quist\n{ids[-2]}|di fox\nx9.9|Ann Lee\n{ids[-3]}|-\nEND|4\n"
    got = asyncio.run(speakers.find_voices(doc, ScriptedClient(lambda r: answer)))
    assert got == {ids[-2]: "di fox"}  # a made-up name, an unknown ID and "-" are dropped


def test_who_reads_in_batches_with_the_lines_before_and_fails_as_a_whole(monkeypatch):
    monkeypatch.setattr(speakers, "WHO_BATCH", 4)
    doc = tagged()
    client = ScriptedClient(who_answer)
    got = asyncio.run(speakers.find_voices(doc, client))
    assert len(client.requests) == -(-len(doc.anchors) // 4)
    assert all("THE LINES JUST BEFORE" in r.document for r in client.requests[1:])
    assert got[list(doc.anchors)[-1]] == "+1 555 010 0199"
    calls = iter(range(100))
    flaky = ScriptedClient(lambda r: CallFailed("down") if next(calls) in (1, 2) else who_answer(r))
    assert asyncio.run(speakers.find_voices(doc, flaky)) is None  # one batch failed twice


CONTEXT = {"bid_name": "Marlow", "team": ["Cy Day"], "buyer_names": ["Contact Bo Kim, Finance"], "other_documents": ["rfp.pdf"]}
LINES = (
    "Ann Lee|OTHER|Fenwick Advisory|BUYER|set up the call for the town\n"
    "Bo Kim|BUYER|Town of Marlow|-|works for the town\n"
    "Cy Day|OURS|Made Up Corp|-|" + "x" * 200 + "\n"
    "Nobody|BUYER|Town of Marlow|-|not a speaker\n"
    "Di Fox|MAYBE|-|-|bad side\n"
    "END|3\n"
)


@pytest.mark.asyncio
async def test_by_model_keeps_good_lines_and_checks_the_rest():
    client = ScriptedClient(lambda r: LINES)
    got = await speakers.by_model(await ainfo(), HEADER, CONTEXT, client)
    assert set(got) == {"Ann Lee", "Bo Kim", "Cy Day"}  # an unknown ID and a bad side are dropped
    assert got["Ann Lee"] == {"side": "other", "organisation": "Fenwick Advisory", "acts_for": "buyer", "reason": "set up the call for the town"}
    assert got["Cy Day"]["organisation"] == ""  # not in the text: dropped
    assert len(got["Cy Day"]["reason"]) == 120
    [req] = client.requests
    assert req.effort == "low" and req.max_output_tokens < 1000
    assert "Ann Lee | Ann Lee | - | - | - | -" in req.document
    assert "Our team: Cy Day" in req.document and "rfp.pdf" in req.document and "Contact Bo Kim" in req.document


@pytest.mark.asyncio
async def test_by_model_returns_none_when_the_call_fails_and_retries_once():
    client = ScriptedClient(lambda r: CallFailed("down"))
    assert await speakers.by_model(await ainfo(), "", CONTEXT, client) is None
    assert len(client.requests) == 2


def test_opening_text_is_speaker_lines_up_to_the_word_limit():
    units = [SourceUnit(f"t{i}.1", "one two three four", "sentence", i, "00:00:0%d" % i, "", "Ann Lee") for i in range(1, 6)]
    text = speakers.opening_text(units, 10)
    assert text.splitlines() == ["Ann Lee: one two three four"] * 2 + ["Ann Lee: one two"]


# --- the bid ---------------------------------------------------------------------------------


MODEL = {
    "Ann Lee": {"side": "other", "organisation": "Fenwick Advisory", "acts_for": "buyer", "reason": "advisor"},
    "Bo Kim": {"side": "buyer", "organisation": "Town of Marlow", "acts_for": "", "reason": "the town"},
    "Cy Day": {"side": "buyer", "organisation": "Northgate Systems", "acts_for": "", "reason": "wrongly"},
    "Di Fox": {"side": "unknown", "organisation": "", "acts_for": "", "reason": "no sign"},
}


def test_proposal_order_team_list_then_model_then_b_fact():
    inf = {"speakers": [{"id": s, "name": s} for s in ("Ann Lee", "Bo Kim", "Cy Day", "Di Fox", "Ed Roe")]}
    got = {s["id"]: s for s in B.propose_speakers(inf, [{"name": "Cy Day"}], ["Ask Ed Roe."], MODEL)}
    assert (got["Cy Day"]["proposed"], got["Cy Day"]["why"]) == ("ours", "team list")
    assert (got["Ann Lee"]["proposed"], got["Ann Lee"]["why"], got["Ann Lee"]["acts_for"]) == ("other", "model: advisor", "buyer")
    assert (got["Bo Kim"]["proposed"], got["Bo Kim"]["organisation"]) == ("buyer", "Town of Marlow")
    assert (got["Di Fox"]["proposed"], got["Di Fox"]["why"]) == ("unknown", "none")  # model said unknown
    assert (got["Ed Roe"]["proposed"], got["Ed Roe"]["why"]) == ("buyer", "B fact")
    also = {s["id"]: s for s in B.propose_speakers({"speakers": [{"id": "Ed Roe", "name": "Ed Roe"}]}, [], ["Ask Ed Roe."], {"Ed Roe": MODEL["Ann Lee"]})}
    assert also["Ed Roe"]["proposed"] == "other"  # the model beats a B fact


def test_other_is_ready_and_level_3_without_unclear_and_unknown_stays_unclear():
    pb = playbooks.load("call-transcript")
    call = {"confirmed": True, "playbook": "call-transcript", "issue_date": "2026-03-02", "speakers_confirmed": True, "voices": {},
            "speakers": [{"side": "other"}, {"side": "buyer"}]}
    assert B.ready(call) == []
    assert B.level_of(pb, ["other"]) == (3, [])
    assert B.level_of(pb, ["other", "ours"]) == (3, [])
    assert B.level_of(pb, ["other", "buyer"]) == (2, [])
    assert B.level_of(pb, ["other", "unknown"]) == (3, ["unclear"])
    assert B.level_of(pb, ["unknown"]) == (3, ["unclear"])


def test_the_stored_answer_re_proposes_and_a_confirmed_call_is_never_changed(tmp_path):
    bid = B.create(tmp_path, "Marlow", "m")
    doc = bid.add_document(HEADER.encode(), "call.txt")
    bid.update_document(doc["no"], playbook="call-transcript")
    assert B.ready(bid.document(doc["no"]))[:1] == ["type not confirmed"] and bid.document(doc["no"])["voices"] is None
    doc = asyncio.run(speakers.read_voices(bid, doc["no"], ScriptedClient(who_answer)))
    assert all(s["proposed"] == "unknown" for s in doc["speakers"])
    doc = bid.set_speaker_model(doc["no"], MODEL)
    got = {s["name"]: s for s in doc["speakers"]}
    assert got["Ann Lee"]["proposed"] == "other" and got["Ann Lee"]["organisation"] == "Fenwick Advisory"
    bid.update_document(doc["no"], confirmed=True)
    m = bid.manifest()
    m["team"] = [{"name": "Cy Day"}]
    bid.save(m)
    doc = bid.refresh_speakers(doc["no"])  # the team list changes the proposal without a new call
    assert {s["name"]: s["proposed"] for s in doc["speakers"]}["Cy Day"] == "ours"
    bid.update_document(doc["no"], speakers=[{"name": s["name"], "side": "other"} for s in doc["speakers"]], speakers_confirmed=True)
    again = bid.set_speaker_model(doc["no"], {})
    assert again["speakers_model"] == MODEL and {s["side"] for s in again["speakers"]} == {"other"}
    with pytest.raises(ValueError):
        bid.update_document(doc["no"], speakers=[{"name": "Ann Lee", "side": "third"}])
    assert bid.set_voices(doc["no"], {})["voices"] == again["voices"]  # confirmed: the voices stay
