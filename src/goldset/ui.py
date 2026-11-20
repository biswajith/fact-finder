"""Streamlit front end: give it JSON records, a description of the JSON, and prompts; get a golden set.

Start with `goldset ui` (or `uv run streamlit run src/goldset/ui.py`). Each run gets its own folder
under runs/, with the inputs saved next to the outputs, so a run can be reopened or resumed.
"""

import asyncio
import io
import json
import os
import re
import zipfile
from datetime import datetime
from pathlib import Path

import streamlit as st
import yaml

from goldset.config import load_config
from goldset.runner import run

RUNS = Path(os.environ.get("GOLDSET_RUNS", "runs"))
CONFIG = Path(os.environ.get("GOLDSET_CONFIG", "goldset.yaml"))


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "_", text.strip().lower()).strip("_") or "prompt"


def _load_env() -> None:
    env = Path(".env")
    if env.exists():
        for line in env.read_text().splitlines():
            k, sep, v = line.partition("=")
            if sep and k.strip() and not k.lstrip().startswith("#"):
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()] if path.exists() else []


def _zip(folder: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in folder.rglob("*"):
            if p.is_file() and "cache" not in p.relative_to(folder).parts:
                z.write(p, p.relative_to(folder).as_posix())
    return buf.getvalue()


def show_results(run_dir: Path) -> None:
    golden, human = _read_jsonl(run_dir / "golden.jsonl"), _read_jsonl(run_dir / "needs_human.jsonl")
    cov_path = run_dir / "coverage.json"
    coverage: dict = json.loads(cov_path.read_text()) if cov_path.exists() else {}
    st.subheader(f"Results: {run_dir.name}")
    a, b, c, d = st.columns(4)
    a.metric("Golden records", len(golden))
    b.metric("Self-corrected", sum(1 for g in golden if g["provenance"]["attempts"] > 1 or g["provenance"]["adjudicated"]))
    c.metric("Needs a human", len(human))
    covered, total = sum(x["covered"] for x in coverage.values()), sum(x["total"] for x in coverage.values())
    d.metric("Coverage", f"{covered / total:.0%}" if total else "n/a", help="Share of coverage units (chunks, fields, enum and "
             "boundary values, nulls, missing keys) that at least one golden record tests.")
    tab_g, tab_c, tab_h, tab_r, tab_d = st.tabs(["Golden records", "Coverage", "Needs human", "Report", "Download"])
    with tab_g:
        if golden:
            st.dataframe([{
                "prompt": g["prompt_id"], "source": g["source_id"], "type": g["case_type"],
                "input": g["case_input"] or "(whole record)", "expected output": g["expected_output"],
                "attempts": g["provenance"]["attempts"], "by": g["provenance"]["written_by"],
            } for g in golden], width="stretch", hide_index=True)
            pick = st.selectbox("Inspect a record", [g["id"] for g in golden])
            st.json(next(g for g in golden if g["id"] == pick), expanded=False)
        else:
            st.info("No accepted records.")
    with tab_c:
        for task_id, cv in coverage.items():
            st.markdown(f"`{task_id}`: {cv['covered']} of {cv['total']} units ({cv['ratio']:.0%})")
            st.dataframe([{"kind": k, "covered": v[0], "total": v[1]} for k, v in sorted(cv["by_kind"].items())], hide_index=True)
            if cv["uncovered"]:
                with st.expander(f"{len(cv['uncovered'])} not covered yet"):
                    st.code("\n".join(cv["uncovered"]), language=None)
        if not coverage:
            st.info("This run has no coverage data.")
    with tab_h:
        for h in human:
            with st.expander(f"{h['id']}: {h['case_type']} ({h['task_id']})"):
                st.write(h.get("note") or "")
                if h.get("candidate"):
                    st.json(h["candidate"], expanded=False)
        if not human:
            st.success("Nothing left for a human.")
    with tab_r:
        st.markdown((run_dir / "report.md").read_text() if (run_dir / "report.md").exists() else "No report yet.")
    with tab_d:
        st.download_button("golden.jsonl", (run_dir / "golden.jsonl").read_bytes() if golden else b"", "golden.jsonl", disabled=not golden)
        st.download_button("needs_human.jsonl", (run_dir / "needs_human.jsonl").read_bytes() if human else b"", "needs_human.jsonl", disabled=not human)
        st.download_button("Whole run folder (.zip)", _zip(run_dir), f"{run_dir.name}.zip")


def main() -> None:
    st.set_page_config(page_title="Golden dataset builder", layout="wide")
    _load_env()
    cfg = load_config(CONFIG)
    st.title("Golden dataset builder")
    st.caption("A planner writes the todo list, Luna workers build each case, the Decisions API and a reasoning "
               "adjudicator check it, and the planner corrects what fails.")

    with st.sidebar:
        st.header("Settings")
        key = st.text_input("OPENAI_API_KEY", type="password", help="Or put it in .env. Kept only in this process.",
                            placeholder="set" if os.environ.get("OPENAI_API_KEY") else "not set")
        if key:
            os.environ["OPENAI_API_KEY"] = key
        cfg.dataset.cases_per_task = st.number_input("Cases per prompt per JSON", 1, 50, cfg.dataset.cases_per_task)
        cfg.dataset.max_items_per_task = max(cfg.dataset.max_items_per_task, cfg.dataset.cases_per_task * 2)
        cfg.loop.max_rounds = st.number_input("Max correction rounds", 1, 10, cfg.loop.max_rounds)
        cfg.loop.max_attempts = st.number_input("Max attempts per case", 1, 10, cfg.loop.max_attempts)
        cfg.models.planner.effort = st.selectbox("Planner / adjudicator effort", ["low", "medium", "high"], index=2)
        cfg.models.adjudicator.effort = cfg.models.planner.effort
        cfg.gate.accept = st.slider("Gate: accept at or above", 0.5, 0.99, cfg.gate.accept)
        st.caption("Large JSON is cut into chunks and planned chunk by chunk; the loop adds cases until coverage is reached.")
        cfg.coverage.target = st.slider("Coverage target", 0.5, 1.0, cfg.coverage.target)
        cfg.dataset.max_items_large = st.number_input("Max cases per large JSON", 10, 500, cfg.dataset.max_items_large)
        cfg.chunking.json_max_leaves = st.number_input("JSON chunk size (leaves)", 50, 2000, cfg.chunking.json_max_leaves, step=50)
        st.divider()
        past = sorted((p for p in RUNS.glob("*") if (p / "report.md").exists()), reverse=True) if RUNS.exists() else []
        opened = st.selectbox("Open a previous run", ["—"] + [p.name for p in past])

    st.subheader("1. JSON records")
    files = st.file_uploader("One or more .json files", type=["json"], accept_multiple_files=True)
    pasted = st.text_area("…or paste one JSON document", height=120, placeholder='{"order_id": "SO-1001", ...}')

    st.subheader("2. What the JSON means")
    gfile = st.file_uploader("Markdown that explains each key", type=["md", "txt"], key="glossary")
    gtext = st.text_area("…or write it here", height=160, placeholder="- `status`: order state code. `SHP` = shipped ...")

    st.subheader("3. Prompts")
    st.caption("Each prompt is run against every JSON record. The planner decides whether a prompt needs one reference "
               "output per record or many test cases.")
    if "n_prompts" not in st.session_state:
        st.session_state.n_prompts = 1
    prompts: list[tuple[str, str, str]] = []
    for i in range(st.session_state.n_prompts):
        with st.container(border=True):
            c1, c2 = st.columns([3, 1])
            name = c1.text_input("Name", value=f"prompt_{i + 1}", key=f"pname{i}")
            fmt = c2.selectbox("Output", ["auto", "text", "json"], key=f"pfmt{i}")
            text = st.text_area("Prompt text", height=140, key=f"ptext{i}")
            if text.strip():
                prompts.append((_slug(name), text.strip(), fmt))
    pfiles = st.file_uploader("…or upload prompt files (.md / .txt, one prompt each)", type=["md", "txt"], accept_multiple_files=True, key="pfiles")
    for f in pfiles or []:
        prompts.append((_slug(Path(f.name).stem), f.getvalue().decode("utf-8").strip(), "auto"))
    c1, c2, _ = st.columns([1, 1, 4])
    if c1.button("Add prompt"):
        st.session_state.n_prompts += 1
        st.rerun()
    if c2.button("Remove last", disabled=st.session_state.n_prompts <= 1):
        st.session_state.n_prompts -= 1
        st.rerun()

    # validate
    records: list[tuple[str, str]] = []
    problems: list[str] = []
    for f in files or []:
        raw = f.getvalue().decode("utf-8")
        try:
            json.loads(raw)
            records.append((Path(f.name).name, raw))
        except ValueError as e:
            problems.append(f"{f.name} is not valid JSON: {e}")
    if pasted.strip():
        try:
            json.loads(pasted)
            records.append(("pasted.json", pasted))
        except ValueError as e:
            problems.append(f"Pasted JSON is not valid: {e}")
    glossary = (gfile.getvalue().decode("utf-8") if gfile else "") or gtext
    if len({p[0] for p in prompts}) < len(prompts):
        problems.append("Two prompts have the same name.")
    for p in problems:
        st.error(p)
    if not glossary.strip():
        st.warning("No description of the JSON: the models will have to guess what keys mean.")

    ready = records and prompts and not problems and os.environ.get("OPENAI_API_KEY")
    st.divider()
    if st.button("Build golden dataset", type="primary", disabled=not ready):
        run_dir = RUNS / datetime.now().strftime("%Y-%m-%d_%H%M%S")
        src, pdir = run_dir / "inputs" / "sources", run_dir / "inputs" / "prompts"
        src.mkdir(parents=True)
        pdir.mkdir(parents=True)
        for name, raw in records:
            (src / name).write_text(raw)
        if glossary.strip():
            (src / "glossary.md").write_text(glossary)
        for name, text, fmt in prompts:
            meta = {"applies_to": ["*.json"], "cases": cfg.dataset.cases_per_task} | ({"output_format": fmt} if fmt != "auto" else {})
            (pdir / f"{name}.md").write_text(f"---\n{yaml.safe_dump(meta)}---\n{text}\n")
        with st.status("Running: plan → work → verify → reconcile", expanded=True) as status:
            try:
                asyncio.run(run(src, pdir, run_dir, cfg, log=status.write))
                status.update(label="Done", state="complete", expanded=False)
            except Exception as e:  # noqa: BLE001 - show any failure in the page
                status.update(label=f"Failed: {type(e).__name__}", state="error")
                st.exception(e)
        st.session_state.last_run = str(run_dir)
    elif not ready:
        st.caption("Needs at least one JSON record, one prompt and an API key.")

    shown = RUNS / opened if opened != "—" else Path(st.session_state["last_run"]) if "last_run" in st.session_state else None
    if shown is not None and (shown / "report.md").exists():
        st.divider()
        show_results(shown)


main()
