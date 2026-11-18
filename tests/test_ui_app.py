"""The Streamlit app, driven headless with AppTest (UI_SPEC.md section 10). No model call:
the Start extraction button is never clicked."""

import json
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from test_ui_data import fact, make_pdf  # noqa: E402

APP = str(Path(__file__).resolve().parents[1] / "src" / "fact_extractor" / "ui" / "app.py")


@pytest.fixture
def app(tmp_path, monkeypatch):
    """Working directory with runs/rfp-1/run_x/{facts,report}.json and one small PDF."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)  # tmp_path has no .env either
    run = tmp_path / "runs" / "rfp-1" / "run_x"
    run.mkdir(parents=True)
    (run / "facts.json").write_text(json.dumps([
        fact("D", "Proposals due 2027-03-03", [("p1.2", 1, "Proposals are due March 3, 2027.")]),
        fact("R", "Vendor shall provide support", [("p1.1", 1, "The vendor shall provide support.")]),
        fact("R", "Vendor keeps records", [("p2.1", 2, "Records are kept.")], flags=["mandatory"]),
    ]))
    (run / "report.json").write_text(json.dumps({
        "run_id": "run_x", "doc_id": "rfp-1", "pages": 2, "seconds": {"extract": 1.0, "total": 2.0},
        "output_tokens": 10, "cache_hit_calls_2_to_n": 1.0, "failed_calls": [],
        "calls": [{"name": "A", "kind": "extract", "status": "ok", "seconds": 1.0, "lines": 1, "retries": 0,
                   "log": [], "output": "D|x|p1.2|\nEND|1", "usage": {"output_tokens": 10}}],
    }))
    make_pdf(run / "source.pdf")
    make_pdf(tmp_path / "rfp-1.pdf")
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    return at


def fact_cards(at):
    """The open fact's card (style.fact_card), as HTML text; the stylesheet is not a card."""
    return [str(h.proto) for h in at.get("html") if "fx-fact" in str(h.proto) and "<style>" not in str(h.proto)]


def count_line(at):
    return next(t.value for t in at.text if t.value.endswith(" facts") and " of " in t.value)


def test_app_starts_on_a_run(app):
    assert not app.exception
    assert count_line(app) == "3 of 3 facts"


def test_app_opens_the_first_fact(app):
    # The facts list is never left without a source panel: the first fact is open, with its page.
    assert len(fact_cards(app)) == 1 and "Vendor shall provide support" in fact_cards(app)[0]  # p1.1 comes first
    assert len(app.get("image")) == 1


def test_category_filter_changes_count(app):
    run_key = next(b.key for b in app.button if b.key and b.key.startswith("fact-")).split("-")[3]
    app.session_state[f"f_cat::{run_key}"] = ["D"]
    app.run()
    assert not app.exception
    assert count_line(app) == "1 of 3 facts"
    assert "Proposals due 2027-03-03" in fact_cards(app)[0]


def test_opening_a_fact_shows_it(app):
    # The card is the button: the open fact's key says "on", the others "off".
    cards = [b for b in app.button if b.key and b.key.startswith("fact-")]
    assert [b.key.split("-")[1] for b in cards] == ["on", "off", "off"]
    assert "Vendor keeps records" in cards[2].label and "mandatory" in cards[2].label
    cards[2].click().run()
    assert not app.exception
    assert len(fact_cards(app)) == 1 and "Vendor keeps records" in fact_cards(app)[0]
    assert [b.key.split("-")[1] for b in app.button if b.key and b.key.startswith("fact-")] == ["off", "off", "on"]
    assert not [b for b in app.button if b.label in ("Open", "Open ›")]
    assert len(app.get("image")) == 1


def test_start_button_needs_the_checkbox(app, monkeypatch):
    start = lambda: next(b for b in app.button if b.label == "Start extraction")  # noqa: E731
    assert start().disabled  # no key, no PDF, no deal ID
    monkeypatch.setenv("OPENAI_API_KEY", "test-not-a-key")
    app.selectbox(key="new_pick").set_value("rfp-1.pdf")
    app.text_input(key="new_deal").set_value("deal_1")
    app.run()
    assert not app.exception
    assert start().disabled  # everything but the checkbox
    app.checkbox(key="new_confirm").check().run()
    assert not app.exception
    assert not start().disabled
    assert not (Path("runs") / ".staging").exists()  # planning the calls left nothing behind
