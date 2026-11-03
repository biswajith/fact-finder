from fact_extractor import planner
from fact_extractor.planner import PlanConfig
from fact_extractor.tagging import Heading, Page, Paragraph, tag_pages


def test_candidates(doc):
    c = planner.candidates(doc)
    assert "p2.1" in c and "p2.t1r1" in c  # "shall" sentence, compliance table row
    assert "p1.1" not in c and "p1.h1" not in c


def _doc(per_page: list[tuple[str, int]]):
    pages = []
    last = None
    for i, (section, n) in enumerate(per_page, start=1):
        blocks = []
        if section != last:
            blocks.append(Heading(section))
            last = section
        blocks += [Paragraph.of(f"The vendor shall do task {i}-{k}.") for k in range(n)]
        pages.append(Page(i, str(i), blocks))
    return tag_pages("d", pages)


def test_ranges_group_to_target_and_keep_sections():
    d = _doc([("A", 15), ("A", 15), ("B", 20), ("B", 10), ("C", 5)])
    # A=30, B=30, C=5 -> [A] then B does not fit with A (60 > 40), [B, C] = 35
    assert planner.requirement_ranges(d, PlanConfig(40, 60)) == [(1, 2), (3, 5)]


def test_big_section_is_split_by_page():
    d = _doc([("A", 30), ("A", 30), ("A", 30)])
    assert planner.requirement_ranges(d, PlanConfig(40, 60)) == [(1, 1), (2, 2), (3, 3)]


def test_plan_and_splits(doc):
    calls = planner.plan_calls(doc)
    assert [c.name for c in calls] == ["A", "B", "C", "K1", "K2", "R1"]
    assert calls[5].page_range == (1, 3)
    assert [c.page_range for c in planner.split_call(calls[5])] == [(1, 2), (3, 3)]
    k1, k2 = calls[3], calls[4]
    assert k1.codes == ("C", "Q") and "C = contract" in k1.task
    assert k1.page_range[0] == 1 and k2.page_range[1] == 3 and k1.page_range[1] + 1 == k2.page_range[0]
    assert f"main source text is on pages {k1.page_range[0]} to {k1.page_range[1]}" in k1.task
    # A cut one-category call over the whole document splits by pages.
    b_only = planner.split_call(planner.plan_calls(doc)[1])[0]
    assert [c.page_range for c in planner.split_call(b_only, 3)] == [(1, 2), (3, 3)]
    assert calls[0].codes == ("B", "E", "Q") and "E = evaluation" in calls[0].task
    a_parts = planner.split_call(calls[0])
    assert [c.codes for c in a_parts] == [("B", "Q"), ("E", "Q")]
    assert "Allowed codes: B, Q" in a_parts[0].task and "E =" not in a_parts[0].task
    assert planner.split_call(a_parts[0]) == []


def test_task_prompts_match_spec(doc):
    a = planner.plan_calls(doc)[0].task
    assert a.startswith("TASK A\nAllowed codes: B, E, Q\n\nB = buyer information")
    assert a.endswith("If the evaluation points or weights do not add up, write a Q line.")
