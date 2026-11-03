import os

from fact_extractor.cli import load_env


def test_load_env(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('# comment\nFX_A=one\nexport FX_B="two words"\nFX_C=from-file\n\n')
    monkeypatch.delenv("FX_A", raising=False)
    monkeypatch.delenv("FX_B", raising=False)
    monkeypatch.setenv("FX_C", "from-shell")
    load_env(str(env))
    assert os.environ["FX_A"] == "one"
    assert os.environ["FX_B"] == "two words"
    assert os.environ["FX_C"] == "from-shell"  # real environment wins
    monkeypatch.delenv("FX_A")
    monkeypatch.delenv("FX_B")
    load_env(str(tmp_path / "missing"))  # no file is fine
