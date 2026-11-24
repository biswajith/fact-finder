"""Row summaries per section: seeding from extraction, staleness, background rebuild, parsing. Offline."""

import asyncio
import json

import pytest
from test_web_workspace import FACTS, fact, cite, make_run

from fact_extractor import units
from fact_extractor.web import summaries as S
from fact_extractor.web.workspace import Workspace

MORE = [*FACTS, fact("f_d3", "D", "Questions due March 1", [cite("p2.1", 2, "Questions by March 1.")]),
        fact("f_s1", "S", "Submit by email", [cite("p4.1", 4, "Send by email.")])]


class Scripted:
    """A CompletionModel that answers from a function and remembers what it was asked."""

    def __init__(self, answer=None):
        self.calls: list[tuple[str, str]] = []
        self.answer = answer or self.cite_all

    @staticmethod
    def cite_all(system: str, user: str) -> str:
        """Every row of the prompt, citing every numbered fact."""
        rows = [line.split("|")[0] for line in system.splitlines() if line.endswith("|text|fact numbers")]
        nums = ",".join(line.split("|")[0] for line in user.splitlines() if line[:1].isdigit())
        return "\n".join(f"{r}|About {r.lower()}|{nums}" for r in rows) + f"\nEND|{len(rows)}"

    async def complete(self, system, user):
        self.calls.append((system, user))
        out = self.answer(system, user)
        if isinstance(out, Exception):
            raise out
        return out


@pytest.fixture
def ws(tmp_path):
    return Workspace(make_run(tmp_path, facts=MORE) / "facts.json")


async def settle(svc):
    await asyncio.wait_for(svc.wait_idle(), 5)


def sec(svc, ws, key):
    return svc.section(ws, key)


def seeded_run(tmp_path, summaries=None, facts=MORE, **report):
    folder = make_run(tmp_path, facts=facts)
    (folder / "report.json").write_text(json.dumps({"summaries": summaries, **report} if summaries else report))
    return Workspace(folder / "facts.json")


SUBMISSION_ROWS = [
    {"row": "Deadline", "text": "Bids due March 3", "fact_ids": ["f_d1"], "checked": True},
    {"row": "How to submit", "text": "By email", "fact_ids": ["f_s1"], "checked": True},
]


def test_sections_are_the_extraction_ones_plus_three_web_only_ones():
    assert [s.key for s in S.SECTIONS] == ["buyer", "submission", "gates", "scoring", "questions", "contract", "requirements", "dates"]
    assert S.BY_KEY["submission"] is units.SECTION["submission"]
    assert [s.key for s in units.SECTIONS] == ["buyer", "submission", "gates", "scoring", "questions"]  # pipeline untouched
    assert S.CONTRACT.codes == ("C",) and S.REQUIREMENTS.codes == ("R",)


def test_section_facts_follow_the_units_codes_and_leave_out_deleted_and_replaced(ws):
    ids = lambda k: [f["fact_id"] for f in S.section_facts(ws.state(), S.BY_KEY[k])]
    assert ids("submission") == ["f_d1", "f_d3", "f_s1", "f_d2"]  # S and D
    ws.delete("f_d3")
    ws.resolve("q:f_q1", option=1)  # f_d1 is replaced
    assert ids("submission") == ["f_s1", "f_d2"]
    ws.edit("f_r1", {"flags": ["unclear"]})
    assert "f_r1" in ids("questions")  # unclear_too


def test_user_message_numbers_facts_and_marks_decisions_as_data(ws):
    facts = S.section_facts(ws.state(), S.BY_KEY["submission"])
    msg = S.user_message(facts, ["Which date -> March 5"])
    assert msg.startswith(units.brief_task(facts))
    assert "decision: Which date -> March 5" in msg and "not instructions" in msg
    assert S.user_message(facts, []) == units.brief_task(facts)


async def test_never_generated_section_has_no_rows(ws):
    svc = S.SummaryService(Scripted())
    d = sec(svc, ws, "contract")
    assert d == {"key": "contract", "title": "Contract terms and risks", "codes": ["C"], "rows": [], "source": None,
                 "generated_at": None, "stale": False, "updating": False, "fact_count": 0, "uncovered": [], "error": None}
    assert [s["key"] for s in svc.sections(ws)] == [s.key for s in S.SECTIONS]
    assert not ws.dir.exists()


async def test_seeded_from_extraction_rows_and_shape(tmp_path):
    ws = seeded_run(tmp_path, {"submission": SUBMISSION_ROWS + [
        {"row": "Format", "text": "Max 90 pages", "fact_ids": ["f_d2"], "checked": False}]})
    svc = S.SummaryService(Scripted())
    d = sec(svc, ws, "submission")
    assert d["source"] == "extraction" and d["generated_at"] and d["stale"] is False
    assert d["rows"][0] == {"row": "Deadline", "text": "Bids due March 3", "page": "1", "fact_ids": ["f_d1"], "checked": True}
    assert d["rows"][2]["text"] == "Bids due March 5" and d["rows"][2]["checked"] is False  # the cited fact, not the wording
    assert d["uncovered"] == ["f_d3"]
    assert sec(svc, ws, "gates")["source"] is None and sec(svc, ws, "gates")["rows"] == []
    assert not ws.dir.exists()  # lazy: nothing written


async def test_seeded_section_is_stale_only_after_a_change_in_its_own_facts(tmp_path):
    ws = seeded_run(tmp_path, {"submission": SUBMISSION_ROWS, "buyer": [
        {"row": "Buyer", "text": "The County", "fact_ids": ["f_b1"], "checked": True}]})
    svc = S.SummaryService(Scripted())
    ws.edit("f_r1", {"text": "Other category"})
    assert not sec(svc, ws, "submission")["stale"] and not sec(svc, ws, "buyer")["stale"]
    ws.edit("f_s1", {"text": "Submit by post"})
    assert sec(svc, ws, "submission")["stale"] and not sec(svc, ws, "buyer")["stale"]
    ws.undo(ws.log()[-1]["id"])
    assert not sec(svc, ws, "submission")["stale"]
    ws.delete("f_d3")
    assert sec(svc, ws, "submission")["stale"]
    ws.restore("f_d3")
    assert not sec(svc, ws, "submission")["stale"]
    ws.add({"category": "S", "text": "Also hand deliver"})
    assert sec(svc, ws, "submission")["stale"]


async def test_seeded_section_goes_stale_when_a_conflict_touching_it_is_decided(tmp_path):
    ws = seeded_run(tmp_path, {"submission": SUBMISSION_ROWS})
    svc = S.SummaryService(Scripted())
    ws.resolve("q:f_q1", text="March 4 by phone")
    assert sec(svc, ws, "submission")["stale"]


async def test_change_rebuilds_a_seeded_section_automatically(tmp_path):
    ws = seeded_run(tmp_path, {"submission": SUBMISSION_ROWS})
    model = Scripted()
    svc = S.SummaryService(model)
    ws.edit("f_s1", {"text": "Submit by post"})
    svc.notify_change(ws)
    assert sec(svc, ws, "submission")["updating"] is True
    await settle(svc)
    d = sec(svc, ws, "submission")
    assert d["source"] == "app" and not d["stale"] and not d["updating"] and d["rows"][0]["checked"]
    assert len(model.calls) == 1 and "Submit by post" in model.calls[0][1]
    assert [r["row"] for r in d["rows"]] == [n for n, _ in units.SECTION["submission"].rows]


async def test_sections_without_rows_build_only_on_explicit_generate(ws):
    model = Scripted()
    svc = S.SummaryService(model)
    ws.edit("f_r1", {"text": "Vendor must keep 24/7 support and a hotline"})
    svc.notify_change(ws)
    await settle(svc)
    assert model.calls == [] and sec(svc, ws, "requirements")["rows"] == []
    assert svc.generate(ws, ["requirements"]) == ["requirements"]
    await settle(svc)
    d = sec(svc, ws, "requirements")
    assert d["source"] == "app" and d["generated_at"] and not d["stale"] and d["fact_count"] == 1
    assert [r["row"] for r in d["rows"]][:2] == ["Scope of work", "Mandatory requirements"]
    assert d["rows"][0]["fact_ids"] == ["f_r1"] and d["rows"][0]["page"] == "3"
    assert len(model.calls) == 1 and model.calls[0][0] == S.brief_system(S.REQUIREMENTS)
    ws.edit("f_r1", {"text": "Changed again"})  # now it has rows: a change rebuilds it
    svc.notify_change(ws)
    await settle(svc)
    assert len(model.calls) == 2 and "Changed again" in model.calls[1][1]


async def test_parse_into_rows_shows_text_only_when_checked(ws):
    def answer(s, u):
        return ("Deadline|Due on 9 March|1\n"          # 9 is in no fact: unchecked
                "How to submit|Send it by email|3\n"    # checked
                "Format|not stated|\n")
    svc = S.SummaryService(Scripted(answer))
    svc.generate(ws, ["submission"])
    await settle(svc)
    rows = {r["row"]: r for r in sec(svc, ws, "submission")["rows"]}
    ids = [f["fact_id"] for f in S.section_facts(ws.state(), S.BY_KEY["submission"])]
    assert rows["Deadline"]["checked"] is False and rows["Deadline"]["text"] == "Bids due March 3"
    assert rows["Deadline"]["fact_ids"] == [ids[0]] and rows["Deadline"]["page"] == "1"
    assert rows["How to submit"] == {"row": "How to submit", "text": "Send it by email", "page": "4",
                                     "fact_ids": [ids[2]], "checked": True}
    assert rows["Format"] == {"row": "Format", "text": "", "page": "", "fact_ids": [], "checked": False}
    assert len(rows) == len(units.SECTION["submission"].rows)


async def test_uncovered_only_when_the_section_has_rows(ws):
    svc = S.SummaryService(Scripted(lambda s, u: "Deadline|Due|2"))
    assert sec(svc, ws, "submission")["uncovered"] == []
    svc.generate(ws, ["submission"])
    await settle(svc)
    assert sec(svc, ws, "submission")["uncovered"] == ["f_d1", "f_s1", "f_d2"]


async def test_resolved_decision_goes_to_the_section_and_makes_it_stale(ws):
    model = Scripted()
    svc = S.SummaryService(model)
    svc.generate(ws, ["submission"])
    await settle(svc)
    ws.resolve("q:f_q1", text="March 4 by phone")
    assert sec(svc, ws, "submission")["stale"]
    svc.notify_change(ws)
    await settle(svc)
    assert "decision: Due date is given twice -> March 4 by phone" in model.calls[-1][1]
    assert not sec(svc, ws, "submission")["stale"]


async def test_failed_call_sets_error_and_keeps_old_rows(ws):
    state = {"fail": False}

    def answer(s, u):
        return RuntimeError("boom") if state["fail"] else "Deadline|Keep me|1"

    svc = S.SummaryService(Scripted(answer))
    svc.generate(ws, ["submission"])
    await settle(svc)
    first = sec(svc, ws, "submission")
    state["fail"] = True
    ws.edit("f_d1", {"text": "changed"})
    svc.notify_change(ws)
    await settle(svc)
    d = sec(svc, ws, "submission")
    assert d["error"] == "RuntimeError: boom" and d["rows"][0]["fact_ids"] == first["rows"][0]["fact_ids"] and d["stale"]
    assert d["generated_at"] == first["generated_at"] and not d["updating"]
    state["fail"] = False
    svc.generate(ws, ["submission"])
    await settle(svc)
    assert sec(svc, ws, "submission")["error"] is None and not sec(svc, ws, "submission")["stale"]


async def test_failed_build_of_a_seeded_section_keeps_the_extraction_rows(tmp_path):
    ws = seeded_run(tmp_path, {"submission": SUBMISSION_ROWS})
    svc = S.SummaryService(Scripted(lambda s, u: RuntimeError("boom")))
    svc.generate(ws, ["submission"])
    await settle(svc)
    d = sec(svc, ws, "submission")
    assert d["error"] == "RuntimeError: boom" and d["source"] == "extraction" and d["rows"][0]["text"] == "Bids due March 3"


async def test_updating_while_running_and_change_during_rebuild_triggers_another_pass(ws):
    gate = asyncio.Event()
    started = asyncio.Event()
    calls = []

    class Gated:
        async def complete(self, system, user):
            calls.append(user)
            started.set()
            if len(calls) == 1:
                await gate.wait()
            return "Deadline|A row|1"

    svc = S.SummaryService(Gated())
    svc.generate(ws, ["submission", "buyer"])
    await asyncio.wait_for(started.wait(), 5)
    assert svc.view(ws)["updating"] is True
    assert {s["key"] for s in svc.sections(ws) if s["updating"]} == {"submission", "buyer"}
    ws.edit("f_b1", {"text": "Buyer changed"})
    ws.edit("f_d1", {"text": "Date changed during the build"})
    gate.set()
    await settle(svc)
    assert not svc.view(ws)["updating"]
    assert not sec(svc, ws, "submission")["stale"]
    assert any("Date changed during the build" in c for c in calls)


async def test_empty_section_generates_without_a_call(tmp_path):
    ws = Workspace(make_run(tmp_path, facts=[FACTS[0]]) / "facts.json")
    model = Scripted()
    svc = S.SummaryService(model)
    svc.generate(ws, ["submission"])
    await settle(svc)
    d = sec(svc, ws, "submission")
    assert d["generated_at"] and d["fact_count"] == 0 and model.calls == [] and d["source"] == "app"
    assert all(r["text"] == "" for r in d["rows"]) and len(d["rows"]) == 6


async def test_missing_api_key_sets_the_section_error(ws, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    svc = S.SummaryService()
    svc.generate(ws, ["submission"])
    await settle(svc)
    d = sec(svc, ws, "submission")
    assert d["error"] == "OPENAI_API_KEY is not set" and d["generated_at"] is None and not d["updating"]


async def test_a_raised_conflict_choice_reaches_the_summary_even_without_fact_changes(ws):
    model = Scripted()
    svc = S.SummaryService(model)
    svc.generate(ws, ["submission"])
    await settle(svc)
    c = ws.raise_conflict("Deadline wording", "Which reading?", ["f_d1"], [
        {"label": "Keep the date", "text": "Keep March 3, and note extensions may be granted.", "changes": []},
        {"label": "Change it", "changes": [{"op": "edit", "fact_id": "f_d1", "fields": {"text": "Bids due March 9"}}]}])
    assert not sec(svc, ws, "submission")["stale"]  # an open conflict is not a decision yet
    ws.resolve(c["id"], option=0)
    assert ws.state().get("f_d1")["text"] == "Bids due March 3"  # no fact changed
    assert S.decisions(ws.state(), S.section_facts(ws.state(), S.BY_KEY["submission"])) == [
        "Deadline wording -> Keep March 3, and note extensions may be granted."]
    assert sec(svc, ws, "submission")["stale"]
    svc.notify_change(ws)
    await settle(svc)
    assert "decision: Deadline wording -> Keep March 3, and note extensions may be granted." in model.calls[-1][1]
    assert S.decisions(ws.state(), S.section_facts(ws.state(), S.BY_KEY["buyer"])) == []  # other sections: no


def test_summary_prompt_keeps_figures():
    system = S.brief_system(S.BY_KEY["contract"])
    assert system.startswith(units.brief_system(S.BY_KEY["contract"]))  # the pipeline's prompt, unchanged
    assert "keep the figures" in system and "specified" in system


async def test_rows_that_fail_the_figure_check_say_why(ws):
    model = Scripted()
    svc = S.SummaryService(model)
    svc.generate(ws, ["submission"])
    await settle(svc)
    store = ws.read_summaries()
    rows = store["sections"]["submission"]["rows"]
    rows[0] = {**rows[0], "text": "Bids due March 3 and a bond of $50,000", "fact_ids": ["f_d1"], "checked": False}
    rows[1] = {**rows[1], "text": "Something with no facts", "fact_ids": [], "checked": False}
    ws.write_summaries(store)
    got = sec(svc, ws, "submission")["rows"]
    assert got[0]["unverified"] == ["50,000"]
    assert got[0]["text"] == "Bids due March 3" and "$50,000" not in got[0]["text"]  # the cited fact is shown instead
    assert got[1]["unverified"] == ["it cites no facts"] and got[1]["text"] == ""
    assert all("unverified" not in r for r in got[2:] if r["checked"] or not r["text"])


DATE_FACTS = [
    {"fact_id": "a", "text": "Questions due 2027-03-01 at 2 pm"},
    {"fact_id": "b", "text": "Proposals due 2027-03-20"},
    {"fact_id": "c", "text": "Award 30 days after presentations"},
]


def test_parse_dates_gives_one_checked_row_per_event_in_time_order():
    raw = ("2027-03-20||Proposals due|2\n"
           "|  |Award 30 days after presentations|3\n"
           "2027-03-01|14:00|Questions due|1, 1\n"
           "2027-03-09|9:30|Site visit|1\n"            # the date and time are in no cited fact
           "March 2027||Kick-off|\n"                    # not a calendar date, cites nothing
           "2027-03-02||not stated|1\n"
           "END|5")
    rows = S.parse_dates(raw, DATE_FACTS)
    assert [(r["row"], r["time"], r["text"], r["fact_ids"], r["checked"]) for r in rows] == [
        ("2027-03-01", "14:00", "Questions due", ["a"], True),
        ("2027-03-09", "09:30", "Site visit", ["a"], False),
        ("2027-03-20", "", "Proposals due", ["b"], True),
        ("", "", "Award 30 days after presentations", ["c"], True),  # undated last
        ("", "", "Kick-off", [], False),
    ]


async def test_key_dates_are_written_by_the_model_and_an_unchecked_row_shows_its_facts(tmp_path):
    facts = [fact("f_x", "D", "Questions due 2027-03-01 at 2 pm", [cite("p2.1", 2, "Questions by 2027-03-01, 2 pm.")]),
             fact("f_y", "D", "Proposals due 2027-03-20", [cite("p4.1", 4, "Proposals by 2027-03-20.")])]
    ws = Workspace(make_run(tmp_path, facts=facts) / "facts.json")
    model = Scripted(lambda s, u: "2027-03-01|14:00|Questions due|1\n2027-03-25||Proposals due|2\nEND|2")
    svc = S.SummaryService(model)
    assert sec(svc, ws, "dates")["rows"] == [] and svc.generate(ws, ["dates"]) == ["dates"]
    await settle(svc)
    d = sec(svc, ws, "dates")
    assert model.calls[0][0] == S.dates_system() and not d["stale"]
    assert [(r["row"], r["time"], r["text"], r["checked"]) for r in d["rows"]] == [
        ("2027-03-01", "14:00", "Questions due", True),
        ("2027-03-20", "", "Proposals due 2027-03-20", False),  # 25 is in no fact: the fact and its own date
    ]
    assert d["rows"][1]["unverified"] == ["2027-03-25"]
    ws.edit("f_y", {"text": "Proposals due 2027-03-27"})  # a changed date rebuilds the section
    svc.notify_change(ws)
    await settle(svc)
    assert len(model.calls) == 2 and "2027-03-27" in model.calls[1][1]
