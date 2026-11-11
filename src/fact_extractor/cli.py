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
        ("extract", "run the extraction (needs OPENAI_API_KEY)"),
    ):
        p = sub.add_parser(name, help=help_)
        p.add_argument("pdf")
        p.add_argument("--doc-id", default=None, help="defaults to the file name")
        if name == "extract":
            p.add_argument("--deal-id", required=True)
            p.add_argument("--model", default=None, help="defaults to $FACT_EXTRACTOR_MODEL or gpt-6-luna")
            p.add_argument("--parallel", type=int, default=32)
            p.add_argument("--passes", type=int, default=2, help="extraction passes to merge; 1 is faster, 2 finds more")
            p.add_argument("--narrow-sweep", action="store_true", help="sweep only shall/must sentences (faster)")
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
    args = ap.parse_args(argv)

    if args.cmd == "compare":
        return _compare(args)

    doc_id = args.doc_id or args.pdf.rsplit("/", 1)[-1].rsplit(".", 1)[0]
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
    else:
        from .llm import OpenAIClient

        store = InMemoryFactStore()
        result = asyncio.run(
            extract(
                doc, OpenAIClient(args.model), deal_id=args.deal_id, store=store,
                decisions=RecordingDecisions(),
                cfg=Config(
                    max_parallel=args.parallel, parallel_check=not args.sequential_check,
                    passes=args.passes, sweep_all=not args.narrow_sweep,
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


def _compare(args) -> int:
    from . import compare as cm

    gold = [item for path in args.gold for item in cm.read_lines(path)]
    with open(args.facts) as f:
        found = cm.from_records(json.load(f))
    result = cm.compare(gold, found)
    print(f"{'code':4} {'gold':>5} {'extr':>5} {'recall':>7} {'any code':>8} {'other':>5} {'merged':>6} {'extr~gold':>9}")
    for c in result.categories:
        r = result.by_category[c]
        print(
            f"{c:4} {r['gold']:5} {r['extracted']:5} {r['recall_same_code']!s:>7} {r['recall_any_code']!s:>8} "
            f"{r['found_under_other_code']:5} {r['missed_merged']:6} {r['extracted_matching_gold']!s:>9}"
        )
    total = len(result.matches)
    hit = sum(1 for m in result.matches if m.found)
    print(f"all  {total:5} {len(found):5} recall any code {hit / total:.3f}" if total else "no gold facts")
    if result.merged:
        print(f"{len(result.merged)} missed gold facts were folded into a fact already matched to another gold fact")
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
                            "values": asdict(m.values) if m.values else None,
                        }
                        for m in result.matches if m.found
                    ],
                },
                f, indent=2,
            )
    return 0
