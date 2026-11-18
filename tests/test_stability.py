from fact_extractor.stability import compare_runs


def rec(fid, cat, *ids):
    return {"fact_id": fid, "category": cat, "citations": [{"id": i} for i in ids]}


def test_compare_runs():
    a = [rec("f1", "R", "p1.1"), rec("f2", "C", "p1.2"), rec("f3", "D", "p1.3")]
    b = [rec("f1", "R", "p1.1"), rec("f9", "R", "p1.2"), rec("f8", "C", "p1.2"), rec("f7", "S", "p2.1")]
    r = compare_runs(a, b)
    assert r["cited_both"] == 2 and r["id_agreement"] == 0.5  # p1.1, p1.2 of four IDs
    assert r["same_codes"] == 1 and r["code_agreement"] == 0.5  # p1.2 is C in one run, C and R in the other
    assert r["same_fact_id"] == 1 and r["code_flips"] == [(("", "R"), 1)]
    same = compare_runs(a, a)
    assert same["id_agreement"] == same["code_agreement"] == same["fact_id_agreement"] == 1.0
