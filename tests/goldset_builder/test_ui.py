"""The UI renders, validates input, and shows a finished run."""

import shutil
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from goldset.config import Config
from goldset.runner import run

from .fakes import ScriptedBrain

UI = str(Path(__file__).parent.parent.parent / "src" / "goldset" / "ui.py")
EX = Path(__file__).parent.parent.parent / "examples" / "goldset"


@pytest.fixture
def runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GOLDSET_RUNS", str(tmp_path / "runs"))
    monkeypatch.setenv("GOLDSET_CONFIG", str(tmp_path / "none.yaml"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)  # no .env here
    return tmp_path / "runs"


def test_build_is_disabled_until_inputs_and_key(runs: Path) -> None:
    at = AppTest.from_file(UI, default_timeout=30).run()
    assert not at.exception
    build = next(b for b in at.button if b.label == "Build golden dataset")
    assert build.disabled
    at.text_area[0].input("{not json").run()
    assert any("not valid" in e.value for e in at.error)
    add = next(b for b in at.button if b.label == "Add prompt")
    add.click().run()
    assert len([t for t in at.text_input if t.label == "Name"]) == 2


async def test_opens_a_previous_run(runs: Path) -> None:
    folder = runs / "2026-10-26_000000"
    await run(EX / "sources", EX / "prompts", folder, Config(), brain=ScriptedBrain(), log=lambda _: None)
    at = AppTest.from_file(UI, default_timeout=30).run()
    at.sidebar.selectbox[1].select(folder.name).run()
    assert not at.exception
    assert [m.value for m in at.metric][:3] == ["4", "3", "1"] and at.metric[3].value.endswith("%")
    shutil.rmtree(folder)
