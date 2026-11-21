"""Chat workspace web UI (WEB_UI_SPEC.md): corrections, summaries, a chat agent, a FastAPI app.

Only this file is imported by `import fact_extractor.web`; it needs no FastAPI. The small
helpers below are shared by the modules that talk to a model.
"""

from __future__ import annotations

import os

DEFAULT_MODEL = "gpt-6-luna"


class ModelUnavailable(Exception):
    """No model can be reached (for example the API key is missing). The message is shown to the user."""


def model_name() -> str:
    return os.environ.get("FACT_EXTRACTOR_MODEL", DEFAULT_MODEL)


def has_api_key() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))


def require_api_key() -> None:
    """Raise ModelUnavailable before any client is built, so a missing key is a clear message."""
    if not has_api_key():
        raise ModelUnavailable("OPENAI_API_KEY is not set")
