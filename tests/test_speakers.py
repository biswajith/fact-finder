"""Speakers' sides by the model (speakers.py): the answer checked in code, and how the bid uses it."""

import json

import pytest
from conftest import ScriptedClient

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


def gong_export() -> bytes:
    parties = [
        {"speakerId": "1", "name": "Ann Lee", "emailAddress": "ann@fenwick.example", "title": "Principal", "affiliation": "External"},
        {"speakerId": "2", "name": "Bo Kim", "title": "Analyst", "affiliation": "Internal"},
    ]
    turns = [{"speakerId": s, "topic": "", "sentences": [{"start": 1000 * n, "text": "Hello there."}]} for n, s in enumerate("12", 1)]
    return json.dumps({"extensive": {"calls": [{"metaData": {"title": "t", "started": "2026-03-02T10:00:00Z"}, "parties": parties}]},
                       "transcript": {"callTranscripts": [{"transcript": turns}]}}).encode()


def info():
    return cutters.cut_transcript(HEADER.encode(), "c.txt")[1]


def test_the_header_gives_organisation_title_and_note():
    got = {s["name"]: (s["organisation"], s["title"], s["note"]) for s in info()["speakers"]}
    assert got == {
        "Ann Lee": ("Fenwick Advisory", "Principal", "the town's selection advisor"),
        "Bo Kim": ("Town of Marlow", "Finance Director", ""),
        "Cy Day": ("Northgate Systems", "", ""),
        "Di Fox": ("", "", ""),
        "+1 555-010-0199": ("", "", "joined by phone"),
    }
    assert set(info()["speakers"][0]) >= {"id", "name", "email", "title", "affiliation", "organisation", "note"}


def test_a_gong_export_takes_the_organisation_from_the_email_domain():
    got = cutters.cut_transcript(gong_export(), "c.json")[1]["speakers"]
    assert [(s["name"], s["organisation"], s["title"], s["note"]) for s in got] == [
        ("Ann Lee", "fenwick.example", "Principal", ""), ("Bo Kim", "", "Analyst", "")]


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
    got = await speakers.by_model(info(), "Ann Lee: Welcome all.", CONTEXT, client)
    assert set(got) == {"Ann Lee", "Bo Kim", "Cy Day"}  # an unknown ID and a bad side are dropped
    assert got["Ann Lee"] == {"side": "other", "organisation": "Fenwick Advisory", "acts_for": "buyer", "reason": "set up the call for the town"}
    assert got["Cy Day"]["organisation"] == "Northgate Systems"  # not in the text: the cutter's one stands
    assert len(got["Cy Day"]["reason"]) == 120
    [req] = client.requests
    assert req.effort == "low" and req.max_output_tokens < 1000
    assert "Ann Lee | Ann Lee | Fenwick Advisory | Principal | the town's selection advisor | -" in req.document
    assert "Our team: Cy Day" in req.document and "rfp.pdf" in req.document and "Contact Bo Kim" in req.document


@pytest.mark.asyncio
async def test_by_model_returns_none_when_the_call_fails_and_retries_once():
    client = ScriptedClient(lambda r: CallFailed("down"))
    assert await speakers.by_model(info(), "", CONTEXT, client) is None
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


def test_proposal_order_team_list_then_model_then_b_fact_then_affiliation():
    inf = {"speakers": [
        {"id": s, "name": s, "organisation": "", "title": "", "note": "", "affiliation": a}
        for s, a in (("Ann Lee", ""), ("Bo Kim", ""), ("Cy Day", ""), ("Di Fox", "Internal"), ("Ed Roe", ""))]}
    got = {s["id"]: s for s in B.propose_speakers(inf, [{"name": "Cy Day"}], ["Ask Ed Roe."], MODEL)}
    assert (got["Cy Day"]["proposed"], got["Cy Day"]["why"]) == ("ours", "team list")
    assert (got["Ann Lee"]["proposed"], got["Ann Lee"]["why"], got["Ann Lee"]["acts_for"]) == ("other", "model: advisor", "buyer")
    assert (got["Bo Kim"]["proposed"], got["Bo Kim"]["organisation"]) == ("buyer", "Town of Marlow")
    assert (got["Di Fox"]["proposed"], got["Di Fox"]["why"]) == ("ours", "Gong affiliation")  # model said unknown
    assert (got["Ed Roe"]["proposed"], got["Ed Roe"]["why"]) == ("buyer", "B fact")
    also = {s["id"]: s for s in B.propose_speakers({"speakers": [{"id": "Ed Roe", "name": "Ed Roe"}]}, [], ["Ask Ed Roe."], {"Ed Roe": MODEL["Ann Lee"]})}
    assert also["Ed Roe"]["proposed"] == "other"  # the model beats a B fact


def test_other_is_ready_and_level_3_without_unclear_and_unknown_stays_unclear():
    pb = playbooks.load("call-transcript")
    call = {"confirmed": True, "playbook": "call-transcript", "issue_date": "2026-03-02", "speakers_confirmed": True,
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
    assert all(s["proposed"] == "unknown" for s in doc["speakers"])
    doc = bid.set_speaker_model(doc["no"], MODEL)
    got = {s["name"]: s for s in doc["speakers"]}
    assert got["Ann Lee"]["proposed"] == "other" and got["Ann Lee"]["organisation"] == "Fenwick Advisory"
    assert got["Ann Lee"]["title"] == "Principal" and got["Ann Lee"]["note"] == "the town's selection advisor"
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
