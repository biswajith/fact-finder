"""Command line: tag a PDF, extract and store its facts, score a run, build a reference list, open the web workspace."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict

from .pdf import read_pdf
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
            p.add_argument("--no-xref", action="store_true", help="skip the cross-reference call (references are found by the model and verified in code)")
            p.add_argument("--no-grouping", action="store_true", help="skip the round that groups repeated points and list items")
            p.add_argument("--parallel", type=int, default=None, help="calls at once (default 48)")
            p.add_argument("--no-check", action="store_true", help="skip the model contradiction check")
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
    web = sub.add_parser("web", help="open the chat workspace (corrections, summaries) in a browser (needs the web extra)")
    web.add_argument("--runs", default="runs", help="folder that holds the runs (default: runs)")
    web.add_argument("--port", type=int, default=8765)
    web.add_argument("--reload", action="store_true", help="development: restart the server when its Python code changes")
    ce = sub.add_parser("chat-eval", help="run chat cases against a bid in each planning mode and compare them (spends API tokens unless --list)")
    ce.add_argument("cases", help="the cases file, YAML (evals/chat/durham.yaml)")
    ce.add_argument("--store", default="runs", help="the folder runs and bids are kept in")
    ce.add_argument("--modes", default="direct,light,heavy,auto", help="planning modes to run, comma separated")
    ce.add_argument("--only", default="", help="only these case IDs or kinds, comma separated")
    ce.add_argument("--approval", default="on", choices=["on", "heavy", "off"], help="which modes wait for the customer's approval of a plan")
    ce.add_argument("--repeat", type=int, default=1, help="run each case this many times per mode")
    ce.add_argument("--parallel", type=int, default=4, help="conversations at once")
    ce.add_argument("--out", default=None, help="folder for results.json, report.txt and the session logs; defaults to runs/_chateval/<time>")
    ce.add_argument("--list", action="store_true", help="show the cases and the facts they name; no model call")
    bd = sub.add_parser("bid", help="a bid: several documents about one opportunity, read one by one and listed together")
    bsub = bd.add_subparsers(dest="bid_cmd", required=True)
    b = bsub.add_parser("create", help="start an empty bid")
    b.add_argument("name")
    b.add_argument("--deal-id", default="")
    b = bsub.add_parser("add", help="add files to a bid and show what each looks like")
    b.add_argument("bid")
    b.add_argument("files", nargs="+")
    b.add_argument("--type", default=None, help="the playbook (document type), instead of the proposed one")
    b.add_argument("--number", type=int, default=None, help="issue number, e.g. of an addendum")
    b.add_argument("--date", default=None, help="issue date YYYY-MM-DD")
    b.add_argument("--yes", action="store_true", help="confirm the type, number and date shown")
    b = bsub.add_parser("speakers", help="show or set who is on which side in a call; NAME=buyer|ours|other|unknown")
    b.add_argument("bid")
    b.add_argument("no", type=int)
    b.add_argument("sides", nargs="*", metavar="NAME=side")
    b = bsub.add_parser("run", help="extract every document that is ready, then build the bid's fact list")
    b.add_argument("bid")
    b.add_argument("--votes", type=int, default=None, help="labelling passes per unit (default: the playbook's)")
    b.add_argument("--model", default=None, help="defaults to $FACT_EXTRACTOR_MODEL or gpt-6-luna")
    b = bsub.add_parser("relate", help="ask again for the units RELATE left unanswered, then build the bid's fact list")
    b.add_argument("bid")
    b.add_argument("--no", type=int, default=None, help="only this document number (default: every document)")
    b.add_argument("--model", default=None, help="defaults to $FACT_EXTRACTOR_MODEL or gpt-6-luna")
    b = bsub.add_parser("show", help="the documents of a bid, in issue order, and what each still needs")
    b.add_argument("bid")
    b = bsub.add_parser("eval", help="score a built bid against a key of relations, sides and groups (no model call)")
    b.add_argument("bid")
    b.add_argument("key", help="the key file, JSON")
    for b in bsub.choices.values():
        b.add_argument("--store", default="runs", help="the folder runs and bids are kept in")
    args = ap.parse_args(argv)

    if args.cmd == "bid":
        return _bid(args)
    if args.cmd == "chat-eval":
        return _chat_eval(args)
    if args.cmd == "web":
        return _web(args)
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
    if args.cmd == "extract" and not args.refresh and _show_stored(args, doc_id):
        return 0  # found by the PDF's content: no need to read the PDF again, or to call the model
    doc = tag_pages(doc_id, read_pdf(args.pdf))

    if args.cmd == "tag":
        sys.stdout.write(doc.tagged_text)
    elif args.cmd == "anchors":
        for a in doc.anchors.values():
            print(json.dumps(asdict(a)))
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
        votes=args.votes, statements=not args.no_statements, check=not args.no_check, xref=not args.no_xref, grouping=not args.no_grouping,
    )
    if args.parallel:
        cfg.max_parallel = args.parallel
    result = asyncio.run(units.extract(doc, OpenAIClient(args.model), deal_id=args.deal_id, cfg=cfg))
    saved = store.save(
        args.pdf, sha, units.VERSION, result, result.labels,
        playbook="rfp@1", source_name=os.path.basename(args.pdf), units=doc,
    )
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


def _chat_eval(args) -> int:
    import asyncio
    import time

    from . import chateval

    try:
        if args.list:
            print(chateval.listing(args.store, args.cases))
            return 0
        if not os.environ.get("OPENAI_API_KEY"):
            print("OPENAI_API_KEY is not set (put it in .env or the environment)", file=sys.stderr)
            return 1
        modes = tuple(m.strip() for m in args.modes.split(",") if m.strip())
        if bad := [m for m in modes if m not in chateval.MODES]:
            print(f"unknown mode {bad[0]}; modes: {', '.join(chateval.MODES)}", file=sys.stderr)
            return 2
        out = args.out or os.path.join(args.store, "_chateval", time.strftime("%Y-%m-%d_%H%M%S"))
        results = asyncio.run(chateval.run(
            args.store, args.cases, modes, [x.strip() for x in args.only.split(",") if x.strip()] or None,
            args.approval, args.repeat, args.parallel, out,
            on_result=lambda r: print(f"{'pass' if r.passed else 'FAIL'} {r.case} [{r.mode}] {r.messages} messages, {r.seconds}s",
                                      file=sys.stderr)))
    except (chateval.CaseError, FileNotFoundError) as e:
        print(str(e), file=sys.stderr)
        return 2
    print(chateval.report(results))
    print(f"\nResults, report and session logs: {out}")
    return 0


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


def _web(args) -> int:
    import importlib.util

    missing = [m for m in ("fastapi", "uvicorn") if importlib.util.find_spec(m) is None]
    if missing:
        print(f"The web UI needs the web extra ({missing[0]} is missing): uv sync --extra web", file=sys.stderr)
        return 1
    from .web.server import serve

    try:
        serve(args.runs, args.port, reload=args.reload)
    except KeyboardInterrupt:
        pass
    return 0


def _suggest_speakers(bid, doc: dict) -> dict:
    """For a call with unconfirmed speakers, when a key is set: ask the model who speaks each line (once),
    then who is on which side. Any failure leaves what was there."""
    from . import playbooks
    from .web import has_api_key

    if doc["speakers_confirmed"] or not playbooks.load(doc["playbook"]).spoken or not has_api_key():
        return doc
    try:
        from . import speakers
        from .llm import OpenAIClient

        client = OpenAIClient()
        if not doc.get("voices"):
            doc = asyncio.run(speakers.read_voices(bid, doc["no"], client)) or doc
        if doc["speakers"]:
            doc = asyncio.run(speakers.suggest(bid, doc["no"], client)) or doc
    except Exception:
        pass
    return doc


def _bid(args) -> int:
    from . import bid as B

    if args.bid_cmd == "create":
        made = B.create(args.store, args.name, args.deal_id)
        print(made.bid_id)
        return 0
    bid = B.Bid(args.store, args.bid)
    if not bid.exists():
        print(f"no bid named {args.bid!r} in {args.store}", file=sys.stderr)
        return 1
    if args.bid_cmd == "add":
        code = 0
        for path in args.files:
            try:
                with open(path, "rb") as f:
                    doc = bid.add_document(f.read(), os.path.basename(path))
                fields = {k: v for k, v in (("playbook", args.type), ("issue_number", args.number), ("issue_date", args.date)) if v is not None}
                if args.yes:
                    fields["confirmed"] = True
                if fields:
                    doc = bid.update_document(doc["no"], **fields)
                doc = _suggest_speakers(bid, doc)
            except (ValueError, OSError) as e:
                print(f"{path}: {e}", file=sys.stderr)
                code = 1
                continue
            p = doc["proposed"]
            print(
                f"{doc['no']}  {doc['doc_id']}  {doc['playbook']}  number {doc['issue_number'] or '-'}  "
                f"date {doc['issue_date'] or '-'}  (suggested by {'the model' if p['by'] == 'model' else p['by']}: {p['playbook']})  "
                + ("confirmed" if doc["confirmed"] else "not confirmed; use --yes")
            )
        return code
    if args.bid_cmd == "speakers":
        try:
            doc = bid.document(args.no)
            if not doc["speakers_confirmed"]:
                doc = _suggest_speakers(bid, doc) if not doc.get("voices") else bid.refresh_speakers(args.no)
            if args.sides:
                given = []
                for item in args.sides:
                    name, _, side = item.rpartition("=")
                    given.append({"name": name, "side": side})
                doc = bid.update_document(args.no, speakers=given)
                # a speaker not named takes the proposed side; the sides are then confirmed
                rest = [{"id": s["id"], "side": s["proposed"]} for s in doc["speakers"] if not s["side"]]
                doc = bid.update_document(args.no, speakers=rest, speakers_confirmed=True)
        except (ValueError, KeyError) as e:
            print(e, file=sys.stderr)
            return 1
        for s in doc["speakers"]:
            org = f" [{s['organisation']}]" if s.get("organisation") else ""
            print(f"{s['name']}{org}: {s['side'] or '-'} (proposed {s['proposed']}, {s['why']})")
        print("speakers confirmed" if doc["speakers_confirmed"] else "not confirmed: give NAME=side for the speakers")
        return 0
    if args.bid_cmd == "eval":
        from . import bideval

        try:
            with open(args.key, encoding="utf-8") as f:
                key = json.load(f)
            print(bideval.report(bideval.score(bid, key)))
        except (OSError, ValueError, KeyError, TypeError) as e:
            print(f"cannot score the bid: {e!r}" if isinstance(e, (KeyError, TypeError)) else f"cannot score the bid: {e}", file=sys.stderr)
            return 1
        return 0
    if args.bid_cmd == "show":
        m = bid.manifest()
        print(f"{m['name']} ({m['bid_id']}), deal {m['deal_id']}")
        for d in B.issue_order(m):
            need = B.ready(d)
            print(
                f"{d['no']:>3}  {d['doc_id']}  {d['playbook']}  number {d['issue_number'] or '-'}  date {d['issue_date'] or '-'}  "
                f"{d['status']}" + (f"  needs: {', '.join(need)}" if need and not d["run"] else "")
            )
        return 0
    if args.bid_cmd == "relate":
        return _bid_relate(args, bid)
    # run
    from .llm import OpenAIClient
    from .results import ResultStore

    store = ResultStore(args.store)
    client = None
    code = 0
    for d in B.issue_order(bid.manifest()):
        if d["status"] == "extracted" and d["run"]:
            continue
        need = B.ready(d)
        if need:
            print(f"{d['doc_id']}: left out, {', '.join(need)}", file=sys.stderr)
            continue
        client = client or OpenAIClient(args.model)
        try:
            asyncio.run(B.extract_document(
                bid, d["no"], client, votes=args.votes, store=store,
                on_step=lambda no, step, status, detail: print(f"{d['doc_id']}: {step} {status} {detail}".rstrip(), file=sys.stderr),
            ))
        except Exception as e:
            print(f"{d['doc_id']}: failed: {e}", file=sys.stderr)
            code = 1
    from .web import has_api_key

    if has_api_key():  # no key: the bid is built from what is stored; every pair is recorded as not checked
        from .llm import OpenAIClient
        from .web.consistency import ConsistencyChecker

        client, checker = client or OpenAIClient(args.model), ConsistencyChecker()
    else:
        client, checker = None, None
    facts = asyncio.run(B.settle(
        bid, client, checker, on_step=lambda no, step, status, detail: print(f"bid: {step} {status} {detail}".rstrip(), file=sys.stderr),
    ))
    print(f"{len(facts)} facts in the bid's list: {bid.folder / 'facts.json'}")
    return code


def _bid_relate(args, bid) -> int:
    """`bid relate`: ask again for the units RELATE left unanswered, then settle and build as `bid run` does."""
    from . import bid as B
    from .llm import OpenAIClient
    from .results import ResultStore
    from .web.consistency import ConsistencyChecker

    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set (put it in .env or the environment)", file=sys.stderr)
        return 1
    left = bid.incomplete_relations()
    if args.no is not None:
        if args.no not in {d["no"] for d in bid.manifest()["documents"]}:
            print(f"no document {args.no} in bid {args.bid!r}", file=sys.stderr)
            return 1
        left = {n: u for n, u in left.items() if n == args.no}
    store, client, code = ResultStore(args.store), OpenAIClient(args.model), 0
    for no, unit_ids in left.items():
        try:
            asyncio.run(B.extract_document(bid, no, client, store=store, relate_only=True, only_incomplete=True))
        except Exception as e:
            print(f"d{no}: failed: {e}", file=sys.stderr)
            code = 1
            continue
        print(f"d{no}: {len(unit_ids)} units asked, {len(bid.incomplete_relations().get(no, []))} still unanswered")
    if not left:
        print("no unit is waiting for an answer")
    facts = asyncio.run(B.settle(
        bid, client, ConsistencyChecker(), on_step=lambda no, step, status, detail: print(f"bid: {step} {status} {detail}".rstrip(), file=sys.stderr),
    ))
    print(f"{len(facts)} facts in the bid's list: {bid.folder / 'facts.json'}")
    return code


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
