"""Skip the goldset suite, rather than fail it, when its dependencies are not installed.

They come from the `evals` extra (`uv sync --extra evals`). `collect_ignore_glob` keeps pytest
from importing the test modules at all, which would raise ImportError.
"""
import importlib.util

_NEEDED = ("langgraph", "langchain", "langchain_openai", "pydantic", "typer", "yaml", "jmespath", "streamlit")

collect_ignore_glob: list[str] = []
if any(importlib.util.find_spec(m) is None for m in _NEEDED):
    collect_ignore_glob = ["test_*.py"]
