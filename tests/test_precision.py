import re

from conftest import ScriptedClient

from fact_extractor import precision as pc


def rec(fid, cat, text, ids=("p1.1",)):
    return {
        "fact_id": fid, "category": cat, "text": text, "flags": [],
        "citations": [{"id": i, "section": "1. Intro", "text": f"source {i}"} for i in ids],
    }


RECORDS = [
    rec("f1", "D", "Proposals due 2027-03-03"),
    rec("f2", "D", "Proposals are due 2027-03-03"),
    rec("f3", "R", "Provide 24/7 support", ("p2.1",)),
    rec("f4", "B", "Table of contents", ("p2.2",)),
]


def test_parse_reads_lines_and_ignores_noise():
    got = pc.parse("ok\n1|yes|useful|fine\n2 | PARTLY | noise | vague\n9|yes|useful|out of range", 2)
    assert got[1].supported == "yes" and got[2] == pc.Grade("partly", "noise", "vague")
    assert 9 not in got


def test_score_counts_precision_as_supported_and_useful():
    s = pc.score([("R", pc.Grade("yes", "useful")), ("R", pc.Grade("yes", "noise")), ("D", pc.Grade("no", "useful"))])
    assert s["R"]["precision"] == 0.5 and s["all"]["precision"] == round(1 / 3, 3)
    assert s["all"]["unsupported"] == round(1 / 3, 3) and list(s)[-1] == "all"


def test_sample_covers_every_category_and_labels_round_trip(tmp_path):
    picked = pc.sample(RECORDS, 3, seed=2)
    assert {r["category"] for r in picked} == {"D", "R", "B"}
    path = tmp_path / "s.csv"
    pc.write_sample(picked, str(path))
    text = path.read_text().splitlines()
    rows = [text[0]] + [line.replace(",,,", ",y,x,") for line in text[1:]]
    path.write_text("\n".join(rows) + "\n")
    labels = pc.read_labels(str(path))
    assert len(labels) == len(picked) and labels[0]["supported"] == "yes" and labels[0]["useful"] == "noise"


def test_duplicates_need_shared_id_and_same_code():
    d = pc.duplicates(RECORDS)
    assert d["pairs"] == 1 and d["facts_involved"] == 2


async def test_grade_caches_and_scores(tmp_path):
    def h(req):
        n = len(re.findall(r"^\d+\. FACT", req.task, re.M))
        return "\n".join(f"{i}|yes|useful|ok" for i in range(1, n + 1))

    client = ScriptedClient(h)
    cache = pc.GradeCache(str(tmp_path / "g.json"))
    grades, asked = await pc.grade(RECORDS, client, cache)
    assert asked == 4 and all(g and g.supported == "yes" for g in grades)
    again, asked2 = await pc.grade(RECORDS, client, pc.GradeCache(str(tmp_path / "g.json")))
    assert asked2 == 0 and len(again) == 4
