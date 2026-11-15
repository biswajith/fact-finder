import re

from conftest import ScriptedClient

from fact_extractor.compare import Item, compare
from fact_extractor.judge import VerdictCache, close_calls, compare_with_judge, parse

GOLD = [
    Item("R", "State on the CGL policy that insurance is primary and non-contributory", ["p30.2"], []),
    Item("R", "Comply with County closeout procedures upon termination", ["p31.4"], []),
]
FOUND = [
    # a paraphrase that scores just under the cutoff on wording
    Item("R", "CGL coverage must apply first, without contribution from County insurance", ["p30.2"], []),
    # same passage, different fact
    Item("R", "Termination requires 30 days written notice", ["p31.4"], []),
]


def answer(yes_if: str):
    """Fake judge: 'full' for pairs whose EXTRACTED text contains `yes_if`, else 'no'."""

    def handler(req):
        lines = []
        for n, found in re.findall(r"(\d+)\. REFERENCE: .*\n   EXTRACTED: (.*)", req.task):
            lines.append(f"{n}|{'full' if yes_if in found else 'no'}|test")
        return "\n".join(lines)

    return handler


def test_parse_reads_numbered_lines_and_ignores_noise():
    got = parse("Here you go\n1|full|same rule\n 2 | NO | other fact\n3|partial|no date\n7|full|out of range\n", 3)
    assert got == {1: ("full", "same rule"), 2: ("no", "other fact"), 3: ("partial", "no date")}


def test_close_calls_picks_pairs_near_the_cutoff():
    cmp = compare(GOLD, FOUND)
    assert all(m.found is None for m in cmp.matches)  # both below the cutoff on wording
    pairs = close_calls(cmp, FOUND)
    assert (GOLD[0].text, FOUND[0].text) in pairs


async def test_judge_rescues_paraphrase_and_caches(tmp_path):
    client = ScriptedClient(answer("apply first"))
    cache = VerdictCache(str(tmp_path / "v.json"))
    run = await compare_with_judge(GOLD, FOUND, client, cache)
    m = run.comparison.matches[0]
    assert m.found is FOUND[0] and m.judged == "full"
    assert run.comparison.matches[1].found is None
    assert run.comparison.by_category["R"]["judge_rescued"] == 1
    assert run.asked >= 1 and len(client.requests) == 1

    # second run: everything comes from the cache file, no model call
    again = ScriptedClient(lambda req: AssertionError("should not be called"))
    run2 = await compare_with_judge(GOLD, FOUND, again, VerdictCache(str(tmp_path / "v.json")))
    assert run2.asked == 0 and not again.requests
    assert run2.comparison.matches[0].found is FOUND[0]


async def test_judge_can_reject_a_wording_match(tmp_path):
    gold = [Item("S", "Mark the outside of the envelope with the company name and address", ["p3.7"], [])]
    found = [Item("S", "The envelope must show the RFP name and the company tax ID", ["p3.7"], [])]
    assert compare(gold, found).matches[0].found is not None  # wording alone matches
    run = await compare_with_judge(gold, found, ScriptedClient(answer("nothing")), VerdictCache(None))
    assert run.comparison.matches[0].found is None


async def test_unanswered_pairs_fall_back_to_wording():
    run = await compare_with_judge(GOLD, FOUND, ScriptedClient(lambda req: "no idea"), VerdictCache(None))
    assert run.unanswered >= 1
    assert all(m.found is None for m in run.comparison.matches)


async def test_partial_counts_as_found_and_is_reported():
    def handler(req):
        return "\n".join(f"{n}|partial|detail missing" for n in re.findall(r"(\d+)\. REFERENCE", req.task))

    run = await compare_with_judge(GOLD[:1], FOUND[:1], ScriptedClient(handler), VerdictCache(None))
    m = run.comparison.matches[0]
    assert m.found is FOUND[0] and m.judged == "partial"
    assert run.comparison.by_category["R"]["judge_partial"] == 1


def test_cache_skips_old_format(tmp_path):
    p = tmp_path / "v.json"
    p.write_text('[{"gold": "a", "found": "b", "match": true, "reason": ""}]')
    assert VerdictCache(str(p)).items == {}
