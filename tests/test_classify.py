"""CLASSIFY (classify.py): the rules on small made-up inputs, and the model's answer checked in code."""

import json

import pymupdf
import pytest
from conftest import ScriptedClient

from fact_extractor import classify
from fact_extractor.llm import CallFailed


def pdf(*pages: str) -> bytes:
    doc = pymupdf.open()
    for text in pages:
        doc.new_page().insert_text((72, 72), text)
    return doc.tobytes()


def test_a_plain_pdf_is_an_rfp_with_the_first_date_on_the_first_page():
    got = classify.by_rules("rfp.pdf", pdf("Request for Proposals\nIssued July 20, 2026. Due August 30, 2026."))
    assert got == {"playbook": "rfp", "issue_number": None, "issue_date": "2026-07-20", "by": "rules", "checked": True}


@pytest.mark.parametrize("first, name, number", [
    ("ADDENDUM NO. 3\nDate: 2026-09-02", "change-addendum", 3),
    ("Amendment #12 to the solicitation", "change-addendum", 12),
    ("Addendum number 2: Questions and Answers", "qa-addendum", 2),
    ("Addendum 4 - Q&A from bidders", "qa-addendum", 4),
    ("Addendum to the solicitation", "change-addendum", None),
])
def test_addendum_pdfs(first, name, number):
    got = classify.by_rules("a.pdf", pdf(first, "Addendum No. 9 on page two is not read"))
    assert (got["playbook"], got["issue_number"]) == (name, number)


def test_only_the_first_page_counts():
    assert classify.by_rules("a.pdf", pdf("Request for Proposals", "Addendum No. 2"))["playbook"] == "rfp"


def test_the_rules_read_any_format_and_leave_the_rest_to_the_model():
    txt = b"Date: 2026-08-12\n[00:00:04] Ann Lee: Hello there.\n[00:00:09] Bo Kim: Hi.\n"
    assert classify.by_rules("call.txt", txt) == {"playbook": "rfp", "issue_number": None, "issue_date": "2026-08-12",
                                                  "by": "rules", "checked": True}
    assert classify.by_rules("a.md", b"# Addendum No. 4\n\nQuestions and answers.\n")["playbook"] == "qa-addendum"
    assert classify.by_rules("t.csv", b"Item,Response\nA,\n")["playbook"] == "rfp"
    assert classify.by_rules("n.md", b"# Deal\n\nNo date.\n")["issue_date"] is None


def test_first_text_stops_at_the_word_limit():
    from fact_extractor.api import SourceUnit

    units = [SourceUnit(f"k{i}", "one two three four", "sentence", 1, "1", "") for i in range(5)]
    assert len(classify.first_text(units, 10).split()) == 10


FIRST = "Addendum No. 2\nIssued September 1, 2026.\nThe due date is changed."
RULES = {"playbook": "change-addendum", "issue_number": 1, "issue_date": "2026-01-01", "by": "rules", "checked": True}


async def ask(answer, first=FIRST, rules=RULES):
    client = ScriptedClient(lambda req: answer)
    out = await classify.by_model("a.pdf", first, client, rules=rules)
    return out, client


async def test_the_model_answer_is_kept_when_every_part_checks():
    out, client = await ask("qa-addendum|2|2026-09-01\n")
    assert out == {"playbook": "qa-addendum", "issue_number": 2, "issue_date": "2026-09-01", "by": "model", "checked": True}
    from fact_extractor import playbooks

    assert all(f"{pb.name}: {pb.description}" in client.requests[0].system for pb in playbooks.all())
    assert client.requests[0].document == FIRST


async def test_parts_that_fail_keep_the_rules_value_and_unset_checked():
    out, _ = await ask("not-a-playbook|7|2030-05-05")
    assert out["playbook"] == "change-addendum" and out["issue_number"] == 1 and out["issue_date"] == "2026-01-01"
    assert out["checked"] is False
    out, _ = await ask("rfp|-|-")  # a dash is an honest "none stated", not a failure
    assert (out["playbook"], out["issue_number"], out["issue_date"], out["checked"]) == ("rfp", 1, "2026-01-01", True)
    out, _ = await ask("rfp|2|2026-09-02")  # the date is not in the text read
    assert (out["issue_number"], out["issue_date"], out["checked"]) == (2, "2026-01-01", False)


async def test_a_failed_call_is_retried_once_then_gives_none():
    out, client = await ask(CallFailed("down"))
    assert out is None and len(client.requests) == 2
    calls = []

    def flaky(req):
        calls.append(1)
        return CallFailed("x") if len(calls) == 1 else "rfp|-|-"

    out = await classify.by_model("a.pdf", FIRST, ScriptedClient(flaky))
    assert out["playbook"] == "rfp" and len(calls) == 2


def test_the_prompt_has_no_example_wording():
    text = classify.system()
    assert "PLAYBOOK|issue number or -|date as YYYY-MM-DD or -" in text
    json.dumps(text)
