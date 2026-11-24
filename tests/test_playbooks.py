"""Playbooks (playbooks/*.md): the rfp prompts are pinned byte for byte, the others load and are checked."""

import json
from pathlib import Path

import pytest
from conftest import ScriptedClient, task_name

from fact_extractor import playbooks, units, xref

SNAPSHOT = json.loads((Path(__file__).parent / "fixtures" / "prompt_snapshot.json").read_text(encoding="utf-8"))
FAST = units.Config(backoff_base=0, warmup_timeout=1)


def test_rfp_prompts_are_unchanged():
    ids = ["p1.1", "p1.2"]
    assert units.SYSTEM == SNAPSHOT["SYSTEM"]
    assert playbooks.load("rfp").system() == SNAPSHOT["SYSTEM"]
    assert playbooks.load("reissued-rfp").system() == SNAPSHOT["SYSTEM"]
    assert units.label_task(ids) == SNAPSHOT["label_task"]
    assert units.state_task(ids) == SNAPSHOT["state_task"]
    assert units.CHECK_TASK == SNAPSHOT["CHECK_TASK"]
    assert units.GROUP_SYSTEM == SNAPSHOT["GROUP_SYSTEM"]
    assert xref.TASK == SNAPSHOT["xref_TASK"]
    assert {s.key for s in units.SECTIONS} == set(SNAPSHOT["brief"])
    for sec in units.SECTIONS:
        assert units.brief_system(sec) == SNAPSHOT["brief"][sec.key]


def test_every_playbook_loads():
    assert playbooks.names() == sorted([
        "rfp", "reissued-rfp", "change-addendum", "qa-addendum", "fill-in-template", "call-transcript", "deal-notes",
    ])
    for pb in playbooks.all():
        assert pb.key == f"{pb.name}@{pb.version}" and pb.body and pb.description
        assert pb.system().startswith("You read ") and "{" not in pb.system().replace("[p12.4]", "")
        assert "LABEL" in pb.calls and sorted(pb.precedence) == sorted(pb.codes)
    assert playbooks.load("rfp").sections == tuple(s.key for s in units.SECTIONS)
    assert "PRIORITY = " in playbooks.load("call-transcript").system()
    assert "precedence:" in playbooks.load("change-addendum").system()
    assert "RELATE" in playbooks.load("qa-addendum").calls and "RELATE" not in playbooks.load("rfp").calls


def test_non_rfp_task_texts_say_the_document():
    pb = playbooks.load("call-transcript")
    assert "the RFP" not in units.state_task(["p1.1"], pb) and "the document" in units.state_task(["p1.1"], pb)
    assert "tentative" in units.label_task(["p1.1"], pb)


GOOD = """---
name: x
description: d
reads: a thing
authority: buyer
role: base
codes: [B, D]
calls: [LABEL]
---
Body.
"""


def test_header_parser_accepts_a_minimal_playbook():
    pb = playbooks.parse(GOOD)
    assert pb.codes == ("B", "D") and pb.precedence == ("B", "D") and pb.votes == 3


@pytest.mark.parametrize("old, new, what", [
    ("calls: [LABEL]", "calls: [LABEL, GUESS]", "calls"),
    ("calls: [LABEL]", "calls: [LABEL, RELATE]", "relations"),
    ("calls: [LABEL]", "calls: [LABEL]\nrelations: [EATS]", "relations"),
    ("calls: [LABEL]", "calls: [LABEL]\ncolour: red", "colour"),
    ("codes: [B, D]", "codes: [B, Z]", "'Z'"),
    ("role: base", "role: boss", "role"),
    ("codes: [B, D]", "codes: B, D", "list"),
])
def test_bad_headers_raise(old, new, what):
    with pytest.raises(ValueError, match=what) as e:
        playbooks.parse(GOOD.replace(old, new), "bad.md")
    assert "bad.md" in str(e.value)


def test_missing_header_and_unknown_playbook():
    with pytest.raises(ValueError, match="bad.md"):
        playbooks.parse("no header", "bad.md")
    with pytest.raises(ValueError, match="nope"):
        playbooks.load("nope")


def test_parse_labels_knows_the_playbooks_codes():
    transcript = playbooks.load("call-transcript")
    assert units.parse_labels("p1.1|PRIORITY|tentative", ["p1.1"], transcript) == {"p1.1": (("PRIORITY",), ("tentative",))}
    assert units.parse_labels("p1.1|PRIORITY", ["p1.1"]) == {}
    assert units.parse_labels("p1.1|PRIORITY", ["p1.1"], playbooks.load("rfp")) == {}
    assert units.parse_labels("p1.1|R|tentative", ["p1.1"]) == {"p1.1": (("R",), ())}


async def test_transcript_run_makes_no_check_and_no_xref(doc):
    def handler(req):
        kind = task_name(req)
        if kind in ("LABEL", "STATE"):
            ids = [i.strip() for i in req.task.splitlines()[2].split(",")]
            body = "\n".join(f"{i}|{'QUESTION' if i == 'p1.2' and kind == 'LABEL' else '-'}" for i in ids)
            return body + f"\nEND|{len(ids)}\n"
        return "END|0\n"

    client = ScriptedClient(handler)
    pb = playbooks.load("call-transcript")
    res = await units.extract(doc, client, deal_id="d", cfg=FAST, run_id="r1", playbook=pb)
    kinds = {task_name(r) for r in client.requests}
    assert "CHECK" not in kinds and "XREF" not in kinds and "BRIEF" not in kinds and "LABEL" in kinds
    assert {r.system for r in client.requests if task_name(r) == "LABEL"} == {pb.system()}
    facts = [f for f in res.facts if f["category"] != "Q"]
    assert [(f["category"], f["citations"][0]["id"], f["playbook"]) for f in facts] == [("QUESTION", "p1.2", "call-transcript")]
    assert res.report["playbook"] == "call-transcript@1"
