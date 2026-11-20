"""Command line: tag a PDF, show the call plan, or run the extraction."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict

from . import planner
from .pdf import read_pdf
from .pipeline import Config, RecordingDecisions, extract
from .store import InMemoryFactStore
from .tagging import tag_pages


def load_env(path: str = ".env") -> None:
    """Read KEY=value lines from `path` into the environment, without overriding what is already set."""
    try:
        with open(path) as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.removeprefix("export ").split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


def main(argv: list[str] | None = None) -> int:
    load_env()
    ap = argparse.ArgumentParser(prog="fact-extractor")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, help_ in (
        ("tag", "print the tagged text sent to the model"),
        ("anchors", "print the anchor map as JSON lines"),
        ("plan", "print the planned calls"),
        ("extract", "extract the facts, or show the stored result for this PDF (needs OPENAI_API_KEY to extract)"),
    ):
        p = sub.add_parser(name, help=help_)
        p.add_argument("pdf")
        p.add_argument("--doc-id", default=None, help="defaults to the file name")
        if name == "extract":
            p.add_argument("--deal-id", required=True)
            p.add_argument("--model", default=None, help="defaults to $FACT_EXTRACTOR_MODEL or gpt-6-luna")
            p.add_argument("--votes", type=int, default=3, help="labelling passes per unit; the majority wins")
            p.add_argument("--store", default="runs", help="folder results are kept in and looked up from")
            p.add_argument(
                "--refresh", action="store_true",
                help="extract again even when this PDF already has a stored result, and say what changed",
            )
            p.add_argument("--no-statements", action="store_true", help="show every fact in the RFP's own words")
            p.add_argument("--no-grouping", action="store_true", help="skip the round that groups repeated points and list items")
            p.add_argument(
                "--legacy", action="store_true",
                help="the earlier pipeline, where the model writes the facts; the options below apply to it only",
            )
            p.add_argument("--parallel", type=int, default=None, help="calls at once (default 48, legacy 32)")
            p.add_argument("--passes", type=int, default=1, help="extraction passes to merge; 2 finds a little more, costs ~60%% more")
            p.add_argument("--narrow-sweep", action="store_true", help="sweep only shall/must sentences (faster)")
            p.add_argument("--max-output-tokens", type=int, default=3000, help="output cap per extraction call")
            p.add_argument("--no-sweep", action="store_true", help="skip the coverage sweep (trimming tests)")
            p.add_argument("--no-check", action="store_true", help="skip the model contradiction check (xref still runs)")
            p.add_argument(
                "--sequential-check", action="store_true",
                help="run the contradiction check after the sweep, so it also sees sweep facts (slower)",
            )
            p.add_argument("--out", default="-", help="facts JSON file, - for stdout")
            p.add_argument("--report", default=None, help="write the run report JSON here")
    c = sub.add_parser("compare", help="score extracted facts against a reference list")
    c.add_argument("gold", nargs="+", help="reference files, one CODE|fact|IDs|flags line per fact")
    c.add_argument("--facts", required=True, help="facts JSON written by extract")
    c.add_argument("--show", type=int, default=10, help="misses and extras to list per category")
    c.add_argument("--json", default=None, help="write the full comparison here")
    c.add_argument("--judge", action="store_true", help="ask the model about close calls (needs OPENAI_API_KEY)")
    c.add_argument(
        "--judge-cache", default=None,
        help="verdict cache JSON; defaults to the facts file with .judge.json. Cached pairs are not asked again",
    )
    c.add_argument("--model", default=None, help="judge model; defaults to $FACT_EXTRACTOR_MODEL or gpt-6-luna")
    pr = sub.add_parser("precision", help="how many extracted facts are supported and useful")
    pr.add_argument("facts", help="facts JSON written by extract")
    pr.add_argument("--sample", type=int, default=0, help="write this many random facts to --sample-out for labelling")
    pr.add_argument("--sample-out", default=None, help="CSV to write the sample to (defaults to <facts>.sample.csv)")
    pr.add_argument("--seed", type=int, default=1)
    pr.add_argument("--labels", default=None, help="labelled sample CSV: score it, and compare with model grades")
    pr.add_argument("--grade", action="store_true", help="have the model grade every fact (needs OPENAI_API_KEY)")
    pr.add_argument("--grade-cache", default=None, help="grade cache JSON (defaults to poc/precision.grades.json)")
    pr.add_argument("--model", default=None)
    pr.add_argument("--json", default=None, help="write the scores here")
    sc = sub.add_parser("score", help="score a run against a reference list by source ID (no model call)")
    sc.add_argument("gold", nargs="+", help="reference files, one CODE|fact|IDs|flags line per fact")
    sc.add_argument("--facts", required=True, help="facts JSON written by extract")
    sc.add_argument("--show", type=int, default=10, help="misses to list")
    sc.add_argument("--json", default=None, help="write the full score here")
    st = sub.add_parser("stability", help="how far two runs on the same document agree")
    st.add_argument("a", help="facts JSON of one run")
    st.add_argument("b", help="facts JSON of another run")
    st.add_argument("--show", type=int, default=10, help="code differences to list")
    st.add_argument("--json", default=None, help="write the numbers here")
    g = sub.add_parser("golden", help="build a reference (gold) fact list from a PDF with the golden-dataset builder (needs the evals extra and OPENAI_API_KEY)")
    g.add_argument("pdf")
    g.add_argument("--doc-id", default=None, help="defaults to the file name")
    g.add_argument("--out", default=None, help="folder for the run; defaults to runs/<doc id>/golden")
    g.add_argument("--codes", default="BCGXDSER", help="categories to build, a subset of BCGXDSER (Q is not supported)")
    g.add_argument("--cases", type=int, default=30, help="checked cases to aim for per category")
    g.add_argument("--config", default="goldset.yaml", help="goldset settings; case budgets are raised to fit --cases")
    ui = sub.add_parser("ui", help="open the fact review app in a browser (needs the ui extra)")
    ui.add_argument("--port", type=int, default=None)
    args = ap.parse_args(argv)

    if args.cmd == "ui":
        return _ui(args)
    if args.cmd == "golden":
        return _golden(args)
    if args.cmd == "compare":
        return _compare(args)
    if args.cmd == "score":
        return _score(args)
    if args.cmd == "stability":
        return _stability(args)
    if args.cmd == "precision":
        return _precision(args)

    doc_id = args.doc_id or args.pdf.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    if args.cmd == "extract" and not args.legacy and not args.refresh and _show_stored(args, doc_id):
        return 0  # found by the PDF's content: no need to read the PDF again, or to call the model
    doc = tag_pages(doc_id, read_pdf(args.pdf))

    if args.cmd == "tag":
        sys.stdout.write(doc.tagged_text)
    elif args.cmd == "anchors":
        for a in doc.anchors.values():
            print(json.dumps(asdict(a)))
    elif args.cmd == "plan":
        for c in planner.plan_calls(doc):
            print(f"{c.name:5} codes={','.join(c.codes):8} pages={c.page_range or 'all'}")
        print(f"candidates: {len(planner.candidates(doc))}, ids: {len(doc.anchors)}")
    elif args.legacy:
        _extract_legacy(args, doc)
    else:
        _extract(args, doc)
    return 0



def _write_out(args, facts: list[dict], report: dict) -> None:
    text = json.dumps(facts, indent=2)
    if args.out == "-":
        print(text)
    else:
        with open(args.out, "w") as f:
            f.write(text)
    if args.report:
        with open(args.report, "w") as f:
            json.dump(report, f, indent=2)


def _show_stored(args, doc_id: str) -> bool:
    """Write out the stored result for this PDF, if there is one."""
    from . import results, units

    stored = results.ResultStore(args.store).find(results.pdf_hash(args.pdf), units.VERSION, doc_id)
    if stored is None:
        return False
    _write_out(args, stored.facts(), stored.report())
    print(
        f"stored result {stored.folder} from {stored.meta.get('created')}: {stored.meta.get('facts')} facts. "
        "No model call. Use --refresh to extract again.",
        file=sys.stderr,
    )
    return True


def _extract(args, doc) -> None:
    """Extract and store (units.py, results.py); `_show_stored` has already looked for a stored result."""
    from . import results, units

    from .llm import OpenAIClient

    store = results.ResultStore(args.store)
    sha = results.pdf_hash(args.pdf)
    previous = store.latest(sha, doc.doc_id)
    cfg = units.Config(
        votes=args.votes, statements=not args.no_statements, check=not args.no_check, grouping=not args.no_grouping,
    )
    if args.parallel:
        cfg.max_parallel = args.parallel
    result = asyncio.run(units.extract(doc, OpenAIClient(args.model), deal_id=args.deal_id, cfg=cfg))
    saved = store.save(args.pdf, sha, units.VERSION, result, result.labels)
    _write_out(args, result.facts, result.report)
    r = result.report
    print(
        f"{r['facts']} facts from {r['ids']} units in {r['seconds']['total']} s: "
        f"{r['facts_votes_agreed']} with all {r['votes']} votes agreed, {r['facts_votes_split']} split; "
        f"{r['facts_in_groups']} facts in {sum(r['groups'].values())} groups; "
        f"{r['output_tokens']} output tokens, cache hit {r['cache_hit_calls_2_to_n']}, "
        f"failed calls {r['failed_calls']}, cut calls {r['cut_calls']}, incomplete calls {r['incomplete_calls']}, "
        f"{len(r['retried_calls'])} retried",
        file=sys.stderr,
    )
    print(f"stored in {saved.folder}", file=sys.stderr)
    if previous:
        d = results.diff(previous.facts(), result.facts)
        print(
            f"against {previous.folder}: {d['same']} facts the same, {len(d['recoded'])} with another code, "
            f"{d['added']} new, {d['removed']} gone, {d['flags_changed']} with other flags",
            file=sys.stderr,
        )


def _score(args) -> int:
    from . import compare as cm
    from . import score as sc

    gold = [item for path in args.gold for item in cm.read_lines(path)]
    with open(args.facts) as f:
        result = sc.score(gold, json.load(f))
    print(f"{'code':4} {'gold':>5} {'found':>5} {'recall':>7} {'same code':>9}")
    for c, r in result["by_category"].items():
        print(f"{c:4} {r['gold']:5} {r['found']:5} {r['recall']:7} {r['recall_same_code']:9}")
    print(f"all  {result['gold']:5} recall {result['recall']}, under the reference code {result['recall_same_code']}; "
          f"{result['units_used']} units used")
    for m in result["missed"][: args.show]:
        print(f"  - missed {m['category']} {m['text']} [{m['id']}]")
    if args.json:
        with open(args.json, "w") as f:
            json.dump(result, f, indent=2)
    return 0


def _extract_legacy(args, doc) -> None:
    from .llm import OpenAIClient

    store = InMemoryFactStore()
    result = asyncio.run(
        extract(
            doc, OpenAIClient(args.model), deal_id=args.deal_id, store=store,
            decisions=RecordingDecisions(),
            cfg=Config(
                max_parallel=args.parallel or 32, parallel_check=not args.sequential_check,
                passes=args.passes, sweep_all=not args.narrow_sweep,
                max_output_tokens=args.max_output_tokens, sweep=not args.no_sweep,
                check=not args.no_check,
            ),
        )
    )
    text = json.dumps(result.facts, indent=2)
    if args.out == "-":
        print(text)
    else:
        with open(args.out, "w") as f:
            f.write(text)
    if args.report:
        with open(args.report, "w") as f:
            json.dump(result.report, f, indent=2)
    r = result.report
    perf = r["performance"]
    print(
        f"{r['facts']} facts, {r['by_status']}, {r['seconds']['total']} s, "
        f"cache hit {r['cache_hit_calls_2_to_n']}, failed calls {r['failed_calls']}",
        file=sys.stderr,
    )
    for name in ("call_seconds", "model_seconds", "ttft_seconds", "queue_seconds", "tokens_per_second"):
        st = perf[name]
        extra = f" p5={st['p5']}" if "p5" in st else ""
        print(f"  {name:18} n={st['n']} p50={st['p50']} p95={st['p95']} max={st['max']}{extra}", file=sys.stderr)
    print(f"  extract stage throughput: {perf['extract_stage_tokens_per_second']} tok/s", file=sys.stderr)


def _golden(args) -> int:
    from . import golden
    from .results import safe_name

    if (missing := golden.missing_dependency()) is not None:
        print(f"The golden-dataset builder needs the evals extra ({missing} is missing): uv sync --extra evals", file=sys.stderr)
        return 1
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set (put it in .env or the environment)", file=sys.stderr)
        return 1
    codes = args.codes.upper()
    if not codes or any(c not in golden.CODES for c in codes):
        print(f"--codes takes letters from {golden.CODES}; Q (contradictions) is not supported", file=sys.stderr)
        return 2
    doc_id = args.doc_id or args.pdf.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    out = args.out or os.path.join("runs", safe_name(doc_id), "golden")
    r = golden.build(args.pdf, out, codes, args.cases, args.config, log=lambda m: print(m, file=sys.stderr), doc_id=doc_id)
    print(f"{r['accepted']} reference facts in {r['gold']}: " + ", ".join(f"{c} {n}" for c, n in r["by_code"].items()))
    print("This is a checked sample of the RFP's facts, not every fact: a score against it is recall on the sample.")
    print("goldset coverage (share of the document's sections a checked case touches): "
          + ", ".join(f"{c} {v:.0%}" for c, v in r["coverage"].items()))
    print(f"{r['rejected']} lines refused ({r['rejected_file']}), {r['needs_human']} cases need a human; report: {r['report']}")
    print(f"Next: fact-extractor score {r['gold']} --facts <facts.json>")
    return 0


def _ui(args) -> int:
    import importlib.util
    import subprocess

    if importlib.util.find_spec("streamlit") is None:
        print("Streamlit is not installed. Install the UI extra: uv sync --extra ui", file=sys.stderr)
        return 1
    app = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui", "app.py")
    cmd = [sys.executable, "-m", "streamlit", "run", app]
    if args.port:
        cmd += ["--server.port", str(args.port)]
    try:
        return subprocess.call(cmd)
    except KeyboardInterrupt:
        return 0


def hit_rate(result) -> float:
    return sum(1 for m in result.matches if m.found) / len(result.matches)


def _compare(args) -> int:
    from . import compare as cm

    gold = [item for path in args.gold for item in cm.read_lines(path)]
    with open(args.facts) as f:
        found = cm.from_records(json.load(f))
    if args.judge:
        from . import judge as jd
        from .llm import OpenAIClient

        path = args.judge_cache or os.path.splitext(args.facts)[0] + ".judge.json"
        cache = jd.VerdictCache(path)
        run = asyncio.run(jd.compare_with_judge(gold, found, OpenAIClient(model=args.model), cache))
        result = run.comparison
        lexical = {(m.gold.text, m.found.text) for m in cm.compare(gold, found).matches if m.found}
        rejected = sum(1 for p, v in cache.verdicts().items() if v == "no" and p in lexical)
        partial = sum(1 for m in result.matches if m.found and m.judged == "partial")
        rescued = sum(1 for m in result.matches if m.found and m.judged and m.score < cm.MATCH_SIMILARITY)
        print(
            f"judge: {run.asked} pairs asked, {run.cached} from cache {path}, {run.unanswered} unanswered; "
            f"{rescued} matched below the cutoff, {rejected} wording matches rejected, {partial} found but partial"
        )
        if result.matches:
            full = sum(1 for m in result.matches if m.found and m.judged != "partial")
            print(f"recall any code {hit_rate(result):.3f}, without judge partials {full / len(result.matches):.3f}")
        final = {(m.gold.text, m.found.text): m for m in result.matches if m.found}
        for sign, label, pick in (
            ("+", "matched below the cutoff", lambda v, p: p in final and p not in lexical),
            ("-", "wording match rejected", lambda v, p: v.verdict == "no" and p in lexical),
            ("~", "partial", lambda v, p: v.verdict == "partial" and p in final),
        ):
            shown = [v for v in cache.items.values() if pick(v, (v.gold, v.found))]
            for v in shown[: args.show]:
                print(f"  {sign} {label}: {v.gold}\n      -> {v.found}  ({v.reason})")
    else:
        result = cm.compare(gold, found)
    print(
        f"{'code':4} {'gold':>5} {'extr':>5} {'recall':>7} {'any code':>8} {'other':>5} {'comb':>4} {'merged':>6} "
        f"{'extr~gold':>9}"
    )
    for c in result.categories:
        r = result.by_category[c]
        print(
            f"{c:4} {r['gold']:5} {r['extracted']:5} {r['recall_same_code']!s:>7} {r['recall_any_code']!s:>8} "
            f"{r['found_under_other_code']:5} {r['combined']:4} {r['missed_merged']:6} {r['extracted_matching_gold']!s:>9}"
        )
    total = len(result.matches)
    hit = sum(1 for m in result.matches if m.found)
    print(f"all  {total:5} {len(found):5} recall any code {hit / total:.3f}" if total else "no gold facts")
    n_comb = sum(1 for m in result.matches if m.combined)
    if n_comb:
        print(f"{n_comb} gold facts found inside an extracted fact that also states another gold fact (comb)")
    if result.merged:
        print(f"{len(result.merged)} missed gold facts matched only a fact already paired with another, "
              "and it does not state them fully (merged)")
    print(f"\n{'code':4} {'values':>6} {'wrong':>5} {'incompl':>7} {'recall, values ok':>17}")
    for c in result.categories:
        r = result.by_category[c]
        print(f"{c:4} {r['values_checked']:6} {r['values_wrong']:5} {r['values_incomplete']:7} {r['recall_values_ok']!s:>17}")
    if total:
        ok = sum(1 for m in result.matches if m.found and (m.values is None or m.values.verdict == "ok"))
        print(f"all  recall with values ok {ok / total:.3f}")
    for verdict in ("wrong", "incomplete"):
        bad = [m for m in result.matches if m.values and m.values.verdict == verdict]
        if bad:
            print(f"\nvalue {verdict} ({len(bad)}):")
            for m in bad[: args.show]:
                extra = f", has {m.values.conflicting}" if m.values.conflicting else ""
                print(f"  ! {m.gold.text}\n    -> {m.found.text}  (missing {m.values.missing}{extra})")
    for flag in ("mandatory", "risk"):
        print(f"flag {flag}: {cm.flag_agreement(result, flag)}")
    conf = cm.confusion(result)
    if conf:
        print("filed under another code (gold -> extracted):", dict(conf.most_common()))
    for c in result.categories:
        misses = [m for m in result.matches if m.gold.category == c and not m.found]
        extras = [e for e in result.extras if e.category == c]
        if misses:
            print(f"\nmissed {c} ({len(misses)}):")
            for m in misses[: args.show]:
                print(f"  - {m.gold.text} [{','.join(m.gold.ids)}]")
        if extras:
            print(f"extracted {c}, no gold match ({len(extras)}):")
            for e in extras[: args.show]:
                print(f"  + {e.text} [{','.join(e.ids)}]")
    if args.json:
        with open(args.json, "w") as f:
            json.dump(
                {
                    "by_category": result.by_category,
                    "misses": [asdict(m.gold) for m in result.matches if not m.found],
                    "missed_merged": [asdict(m.gold) for m in result.merged],
                    "extras": [asdict(e) for e in result.extras],
                    "pairs": [
                        {
                            "gold": asdict(m.gold), "found": asdict(m.found), "score": m.score,
                            "values": asdict(m.values) if m.values else None, "combined": m.combined, "judged": m.judged,
                        }
                        for m in result.matches if m.found
                    ],
                },
                f, indent=2,
            )
    return 0


def _print_rates(title: str, rates: dict) -> None:
    print(title)
    print(f"  {'code':4} {'n':>5} {'supported':>9} {'partly':>6} {'unsup':>5} {'noise':>5} {'precision':>9}")
    for c, r in rates.items():
        print(
            f"  {c:4} {r['n']:5} {r['supported']:9} {r['partly']:6} {r['unsupported']:5} {r['noise']:5} {r['precision']:9}"
        )


def _precision(args) -> int:
    from . import precision as pc

    with open(args.facts) as f:
        records = json.load(f)
    out: dict = {"facts": len(records), "duplicates": pc.duplicates(records)}
    d = out["duplicates"]
    print(f"{len(records)} facts; near-duplicate pairs {d['pairs']} ({d['facts_involved']} facts)")
    if args.sample:
        path = args.sample_out or os.path.splitext(args.facts)[0] + ".sample.csv"
        pc.write_sample(pc.sample(records, args.sample, args.seed), path)
        print(f"wrote {args.sample} facts to label: {path} (supported: y/p/n, useful: u/x)")
    rows = pc.read_labels(args.labels) if args.labels else []
    if rows:
        out["labels"] = pc.score_labels(rows)
        _print_rates(f"labelled by a person ({len(rows)} facts):", out["labels"])
    cache = pc.GradeCache(args.grade_cache or "poc/precision.grades.json")
    if args.grade:
        from .llm import OpenAIClient

        grades, asked = asyncio.run(pc.grade(records, OpenAIClient(model=args.model), cache))
        got = [(r["category"], g) for r, g in zip(records, grades) if g is not None]
        print(f"model grades: {asked} facts sent, {len(records) - len(got)} without an answer")
        out["model"] = pc.score(got)
        _print_rates("graded by the model:", out["model"])
    if rows:
        out["agreement"] = pc.agreement(rows, records, cache)
        print(f"model vs person: {out['agreement']}")
    if args.json:
        with open(args.json, "w") as f:
            json.dump(out, f, indent=2)
    return 0


def _stability(args) -> int:
    from . import stability as sb

    with open(args.a) as f:
        a = json.load(f)
    with open(args.b) as f:
        b = json.load(f)
    r = sb.compare_runs(a, b)
    print(f"facts               {r['facts'][0]:5} {r['facts'][1]:5}")
    print(f"cited IDs           {r['cited_ids'][0]:5} {r['cited_ids'][1]:5}  in both {r['cited_both']}  agreement {r['id_agreement']}")
    print(f"same codes per ID   {r['same_codes']} of {r['cited_both']}  agreement {r['code_agreement']}")
    print(f"same fact_id        {r['same_fact_id']}  agreement {r['fact_id_agreement']}")
    print(f"{'code':4} {'A':>5} {'B':>5} {'IDs in both':>11}")
    for c, row in r["by_category"].items():
        print(f"{c:4} {row['a']:5} {row['b']:5} {row['ids_both']:11}")
    for (x, y), n in r["code_flips"][: args.show]:
        print(f"  {n:3} IDs filed {x or '-'} in one run, {y or '-'} in the other")
    if args.json:
        with open(args.json, "w") as f:
            json.dump(r, f, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
