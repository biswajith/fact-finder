"""The golden-set adapter: source rendering, prompts, gold lines, one scripted build, the CLI.

Everything runs offline. Tests that need goldset skip when the `evals` extra is missing.
"""

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

from fact_extractor import cli, compare, golden, prompts
from fact_extractor.tagging import Heading, Page, Paragraph, tag_pages


def big_doc(pages: int = 8, per_page: int = 14):
    """A document that does not fit one goldset chunk: sections of long sentences, plus a table."""
    out = []
    for n in range(1, pages + 1):
        blocks: list = []
        for s in range(2):
            blocks.append(Heading(f"{n}.{s + 1} Section number {n}-{s}"))
            for k in range(per_page // 2):
                blocks.append(Paragraph.of(f"The bidder shall deliver item {n}-{s}-{k} as described in the schedule of work, in full and on time."))
        out.append(Page(n, str(n), blocks))
    return tag_pages("big", out)


# --- source rendering --------------------------------------------------------------------


def test_source_keeps_every_unit_line_and_its_id(doc):
    text = golden.source_text(doc)
    unit_lines = [ln for ln in text.splitlines() if ln and not ln.startswith("#")]
    assert unit_lines == doc.tagged_text.splitlines()
    assert [ln for ln in text.splitlines() if ln.startswith("## ")] == ["## Page 1", "## Page 2", "## Page 3"]
    assert text.endswith("\n") and not text.startswith("\n")


def test_quotes_from_inside_a_unit_are_found_verbatim(doc):
    pytest.importorskip("pydantic")
    pytest.importorskip("yaml")
    from goldset.checks import normalize

    text = normalize(golden.source_text(doc))
    for line in doc.tagged_text.splitlines():
        body = re.sub(r"^\[[^\]]+\] ", "", line)
        assert normalize(body) in text
        assert normalize(body[5:25]) in text


def test_chunker_cuts_between_units_at_block_boundaries():
    pytest.importorskip("pydantic")
    pytest.importorskip("yaml")
    from goldset.chunks import chunk_source
    from goldset.config import ChunkingCfg
    from goldset.schemas import Source

    doc = big_doc()
    text = golden.source_text(doc)
    cfg = ChunkingCfg()
    chunks = chunk_source(Source(id="big.md", kind="text", text=text), cfg)
    lines = text.splitlines()
    assert len(chunks) > 3
    for c in chunks:
        assert c.size <= cfg.text_max_chars  # blocks are half a chunk, so a chunk is never forced over
        assert c.start_line is not None and c.end_line is not None
        before = lines[c.start_line - 2] if c.start_line > 1 else ""
        assert before == "" or lines[c.start_line - 1].startswith("#")  # a cut falls between blocks
        assert lines[c.end_line - 1].strip()  # a chunk ends on text, not on a blank line
    assert any(lines[c.start_line - 1].startswith("## Page") for c in chunks if c.start_line)
    # every unit sits whole in exactly one chunk
    for n, ln in enumerate(lines, 1):
        if ln.startswith("["):
            assert sum(c.start_line <= n <= c.end_line for c in chunks if c.start_line and c.end_line) == 1


def test_a_block_never_outgrows_the_limit():
    doc = big_doc(pages=1, per_page=40)
    blocks = golden.source_text(doc, max_block=600).split("\n\n")
    assert len(blocks) > 3
    assert all(len(b) <= 600 + 120 for b in blocks)  # the limit, plus one line that crossed it


# --- prompts -----------------------------------------------------------------------------


def test_existing_prompt_strings_are_unchanged():
    # The extractor's prompt cache keys on these bytes. Change them on purpose or not at all.
    h = lambda s: hashlib.sha256(s.encode()).hexdigest()[:16]
    assert h(prompts.SYSTEM) == "4bf2be7b7b70bded"
    assert h(json.dumps(prompts.DEFINITIONS, sort_keys=True)) == "240386a79ef19196"
    assert h(repr(prompts.PRECEDENCE)) == "64b933d6ff116e76"


def test_prompt_front_matter_and_definition(tmp_path):
    pytest.importorskip("pydantic")
    pytest.importorskip("yaml")
    from goldset.sources import load_prompts

    for code in golden.CODES:
        (tmp_path / f"{code}.md").write_text(golden.prompt_text(code, 7))
    loaded = {p.id: p for p in load_prompts(tmp_path)}
    assert sorted(loaded) == sorted(golden.CODES)
    for code, p in loaded.items():
        assert p.output_format == "text" and p.cases == 7
        assert prompts.DEFINITIONS[code] in p.text
        assert f"{code}|fact|IDs|flags" in p.text
        assert "NONE" in p.text


def test_prompt_shares_the_extractors_flag_tests_and_leaves_modal_flags_to_code():
    text = golden.prompt_text("C", 5)
    for flag in golden.MODEL_FLAGS:
        line = next(ln for ln in prompts.SYSTEM.splitlines() if ln.startswith(f"- {flag}:"))
        assert line in text
    assert "- mandatory:" not in text and "- desirable:" not in text and "- replaced:" not in text
    assert "Never write mandatory or desirable" in text
    assert "Q line" not in text
    with pytest.raises(ValueError):
        golden.prompt_text("Q", 5)


# --- to_gold -----------------------------------------------------------------------------


def rec(code, unit, output, id_="r"):
    return {"id": f"{id_}-{code}-{unit}", "prompt_id": code, "case_input": unit, "expected_output": output}


def test_to_gold_drops_none_and_keeps_good_lines(doc):
    lines, rejected = golden.to_gold([
        rec("R", "p2.1", "R|System supports 500 concurrent users|p2.1|"),
        rec("R", "p1.1", "NONE"),
    ], doc)
    assert lines == ["R|System supports 500 concurrent users|p2.1|mandatory"] and rejected == []


@pytest.mark.parametrize("output,why", [
    ("C|Pay within 30 days|p2.1|", "not the prompt's code"),
    ("R/C|Pay within 30 days|p2.1|", "not the prompt's code"),
    ("R|Support|p9.9|", "not in the document"),
    ("R|Support|p2.1,p9.9|", "not in the document"),
    ("R|Support||", "no IDs"),
    ("R|Support|p2.2|", "not the case's unit"),
    ("R||p2.1|", "empty"),
    ("R|Support | 24/7|p2.1|", "| character"),
    ("R|Support", "not in the form"),
])
def test_to_gold_rejects(doc, output, why):
    lines, rejected = golden.to_gold([rec("R", "p2.1", output)], doc)
    assert lines == []
    assert len(rejected) == 1 and why in rejected[0]["reason"] and rejected[0]["line"] == output
    assert rejected[0]["id"] == "r-R-p2.1"


def test_to_gold_rejects_a_category_that_was_not_requested(doc):
    lines, rejected = golden.to_gold([rec("S", "p3.1", "S|Page limit 50|p3.1|")], doc, codes="R")
    assert lines == [] and "not requested" in rejected[0]["reason"]


def test_to_gold_flags(doc):
    lines, _ = golden.to_gold([
        rec("R", "p2.1", "R|Support 500 users|p2.1|mandatory, risk, Post-Award,replaced,bogus"),
        rec("R", "p2.2", "R|Provide support|p2.2|unclear"),
        rec("B", "p1.1", "B|City seeks a records system|p1.1|risk"),
    ], doc)
    assert lines == [
        "B|City seeks a records system|p1.1|risk",  # B is not about what binds the bidder: no modal flag
        "R|Support 500 users|p2.1|mandatory,risk,post-award",  # mandatory from the unit's own words, not the model's
        "R|Provide support|p2.2|mandatory,unclear",
    ]


def test_to_gold_takes_the_modal_flag_from_the_main_unit_not_the_model():
    pages = [Page(1, "1", [Paragraph.of("Vendors should offer training."), Paragraph.of("Training is described here.")])]
    d = tag_pages("d", pages)
    lines, _ = golden.to_gold([rec("R", "p1.1", "R|Offer training|p1.1,p1.2|mandatory")], d)
    assert lines == ["R|Offer training|p1.1,p1.2|desirable"]


def test_to_gold_merges_one_unit_under_two_codes_by_precedence(doc):
    lines, _ = golden.to_gold([
        rec("R", "p3.1", "R|Proposals shall not exceed 50 pages|p3.1,p3.2|risk"),
        rec("S", "p3.1", "S|Proposal page limit is 50|p3.1|"),
        rec("B", "p3.1", "B|Pages|p3.1|"),
    ], doc)
    assert lines == ["S/R/B|Proposal page limit is 50|p3.1,p3.2|mandatory,risk"]
    (item,) = _round_trip(lines)
    assert (item.category, item.alt, item.ids) == ("S", ["R", "B"], ["p3.1", "p3.2"])


def test_to_gold_keeps_several_lines_of_a_unit_separate(doc):
    lines, _ = golden.to_gold([
        rec("R", "p2.2", "R|Provide support|p2.2|\nR|Support runs 24/7|p2.2|"),
        rec("C", "p2.2", "C|Support is part of the contract|p2.2|"),
    ], doc)
    assert [ln.split("|")[0] for ln in lines] == ["C", "R", "R"]  # no alternates when the counts differ


def test_to_gold_is_in_document_order(doc, tmp_path):
    lines, _ = golden.to_gold([
        rec("D", "p3.2", "D|Proposals due 2027-03-05|p3.2|"),
        rec("D", "p1.3", "D|Proposals due 2027-03-03 17:00|p1.3|"),
        rec("D", "p2.1", "D|System date|p2.1|"),
    ], doc)
    assert [ln.split("|")[2] for ln in lines] == ["p1.3", "p2.1", "p3.2"]
    assert [i.ids[0] for i in _round_trip(lines, tmp_path)] == ["p1.3", "p2.1", "p3.2"]


def _round_trip(lines, tmp_path=None):
    import tempfile

    folder = Path(tmp_path) if tmp_path else Path(tempfile.mkdtemp())
    path = folder / "gold.txt"
    path.write_text("".join(f"{ln}\n" for ln in lines))
    return compare.read_lines(str(path))


def test_to_gold_round_trips_through_read_lines(doc, tmp_path):
    lines, _ = golden.to_gold([
        rec("R", "p2.1", "R|Support 500 users|p2.1,p2.2|risk"),
        rec("C", "p2.1", "C|Contract support|p2.1|"),
        rec("D", "p1.3", "D|Proposals due 2027-03-03 17:00|p1.3|"),
    ], doc)
    items = _round_trip(lines, tmp_path)
    assert [(i.category, i.alt, i.ids, i.flags) for i in items] == [
        ("D", [], ["p1.3"], []),
        ("C", ["R"], ["p2.1", "p2.2"], ["mandatory", "risk"]),
    ]


# --- build, scripted ----------------------------------------------------------------------

SCRIPT = {
    "R": {
        "p2.1": "R|System must support 500 concurrent users|p2.1|",
        "p2.2": "R|Vendor must provide 24/7 support|p2.2|risk",
        "p1.1": "NONE",
    },
    "C": {
        "p2.1": "C|Support for 500 users is a contract term|p2.1|",
        "p3.1": "C|Wrong code|S|",  # refused: unknown ID
        "p1.2": "NONE",
    },
}


class ScriptedBrain:
    """Plans one case per scripted unit, writes the scripted output with the unit's own text as evidence."""

    def __init__(self, doc):
        from goldset.brain import Ledger

        self.ledger = Ledger()
        self.lines = golden.source_text(doc).splitlines()
        self.requests: list[str] = []

    def _line_no(self, unit):
        return next(n for n, ln in enumerate(self.lines, 1) if ln.startswith(f"[{unit}] "))

    async def structured(self, stage, schema, system, user):
        from goldset.schemas import BlindAnswer, Candidate, Evidence, PlannedItem, TaskPlan

        self.requests.append(stage)
        code = re.search(r"TASK PROMPT \((\w)\)", user)[1]  # type: ignore[index]
        if stage == "plan":
            items = [PlannedItem(span_start_line=self._line_no(u), span_end_line=self._line_no(u), span_pointer=None,
                                 case_type="unit", instruction=f"unit {u}", acceptance=["the line is in the gold format"],
                                 aggregate=False) for u in SCRIPT[code]]
            return TaskPlan(mode="cases", mode_rationale="one case per unit", output_format="text", items=items)
        if stage == "work":
            unit = re.search(r"instruction: unit (\S+)", user)[1]  # type: ignore[index]
            quote = re.sub(r"^\[[^\]]+\] ", "", self.lines[self._line_no(unit) - 1])
            return Candidate(case_input=unit, expected_output=SCRIPT[code][unit], evidence=[Evidence(quote=quote, pointer=None, value_json=None, query=None, result_json=None)], rationale="r")
        if stage == "solve":
            return BlindAnswer(answer="same", answerable=True)
        raise AssertionError(stage)

    async def agent(self, *a, **k):
        raise AssertionError("no tools on a text source")

    async def decide(self, stage, shared, questions):
        from langchain_openai.decisions import ChoiceAnswer, DecisionResponse, Predicate, PredicateAnswer, Usage

        answers = {}
        for name, q in questions.items():
            if isinstance(q, Predicate):
                answers[name] = PredicateAnswer(type="predicate", probability=0.95)
            else:
                answers[name] = ChoiceAnswer(type="choice", choice="equivalent", confidence=0.9,
                                             probabilities={"equivalent": 0.9, "minor_difference": 0.05, "conflict": 0.05})
        return DecisionResponse(model="m", answers=answers, usage=Usage(input_tokens=1))


def test_build_end_to_end_with_a_scripted_brain(doc, tmp_path):
    for m in ("langgraph", "langchain_openai", "langchain", "pydantic", "yaml", "jmespath"):
        pytest.importorskip(m)
    logs: list[str] = []
    brain = ScriptedBrain(doc)
    r = golden.build(None, tmp_path / "g", "CR", 3, tmp_path / "missing.yaml", brain=brain, log=logs.append, doc=doc)

    out = tmp_path / "g"
    assert (out / "input" / "sources" / "rfp-001.md").read_text() == golden.source_text(doc)
    assert sorted(p.name for p in (out / "input" / "prompts").iterdir()) == ["C.md", "R.md"]
    assert (out / "build" / "golden.jsonl").exists() and (out / "build" / "report.md").exists()

    gold = (out / "gold.txt").read_text().splitlines()
    assert gold == [
        "C/R|Support for 500 users is a contract term|p2.1|mandatory",
        "R|Vendor must provide 24/7 support|p2.2|mandatory,risk",
    ]
    assert [i.ids for i in compare.read_lines(str(out / "gold.txt"))] == [["p2.1"], ["p2.2"]]
    assert r["accepted"] == 2 and r["by_code"] == {"C": 1, "R": 1}
    assert r["needs_human"] == 0
    assert r["rejected"] == 1  # goldset accepted the badly formed C case; to_gold refuses it
    (bad,) = [json.loads(ln) for ln in (out / "rejected.jsonl").read_text().splitlines()]
    assert bad["line"] == "C|Wrong code|S|" and "not in the document" in bad["reason"]
    assert set(r["coverage"]) == {"C", "R"} and all(0 <= v <= 1 for v in r["coverage"].values())
    assert r["gold"] == str(out / "gold.txt")
    assert any("units" in m for m in logs)


def test_build_budgets_and_unknown_codes(doc, tmp_path):
    pytest.importorskip("pydantic")
    pytest.importorskip("yaml")
    from goldset.config import Config

    cfg = golden.budgeted(Config(), 40)
    assert cfg.dataset.max_items_per_task == 60 and cfg.dataset.max_items_large == 80
    assert golden.budgeted(Config(), 100).dataset.max_items_large == 150  # raised, never lowered
    assert golden.budgeted(Config(), 1).dataset.max_items_per_task == 14
    with pytest.raises(ValueError, match="Q is not supported"):
        golden.build(None, tmp_path, "RQ", 3, None, doc=doc)


# --- CLI ---------------------------------------------------------------------------------


def test_golden_command_without_the_evals_extra(monkeypatch, capsys):
    import importlib.util

    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a: None if name == "langgraph" else real(name, *a))
    assert cli.main(["golden", "rfp.pdf"]) == 1
    err = capsys.readouterr().err
    assert "uv sync --extra evals" in err and "langgraph" in err


def test_golden_command_needs_a_key(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(golden, "missing_dependency", lambda: None)
    monkeypatch.chdir(tmp_path)  # so load_env finds no .env
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert cli.main(["golden", "rfp.pdf"]) == 1
    assert "OPENAI_API_KEY" in capsys.readouterr().err


def test_golden_command_prints_counts_and_the_next_command(monkeypatch, tmp_path, capsys):
    seen = {}

    def fake_build(pdf, out, codes, cases, config, log=print, doc_id=None, **kw):
        seen.update(pdf=pdf, out=out, codes=codes, cases=cases, config=config, doc_id=doc_id)
        return {"accepted": 5, "by_code": {"C": 2, "R": 3}, "rejected": 1, "needs_human": 2, "coverage": {"C": 1.0, "R": 0.5},
                "gold": f"{out}/gold.txt", "rejected_file": f"{out}/rejected.jsonl", "report": f"{out}/build/report.md"}

    monkeypatch.setattr(golden, "missing_dependency", lambda: None)
    monkeypatch.setattr(golden, "build", fake_build)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert cli.main(["golden", "docs/My RFP.pdf", "--codes", "cr", "--cases", "12"]) == 0
    assert seen == {"pdf": "docs/My RFP.pdf", "out": "runs/My_RFP/golden", "codes": "CR", "cases": 12,
                    "config": "goldset.yaml", "doc_id": "My RFP"}
    out = capsys.readouterr().out
    assert "5 reference facts" in out and "C 2, R 3" in out
    assert "checked sample" in out and "not every fact" in out
    assert "C 100%, R 50%" in out and "1 lines refused" in out
    assert "fact-extractor score runs/My_RFP/golden/gold.txt --facts <facts.json>" in out


def test_golden_command_refuses_q_and_unknown_codes(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(golden, "missing_dependency", lambda: None)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert cli.main(["golden", "rfp.pdf", "--codes", "RQ"]) == 2
    assert "Q" in capsys.readouterr().err


def test_importing_golden_does_not_import_goldset():
    import subprocess

    code = "import sys, fact_extractor.golden; assert not any(m.split('.')[0] == 'goldset' for m in sys.modules)"
    subprocess.run([sys.executable, "-c", code], check=True)
