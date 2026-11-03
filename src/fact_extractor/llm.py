"""Model client. One request = system prompt, document message, task message (spec 5.2)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Protocol

from .models import Usage


class RateLimited(Exception):
    """HTTP 429."""


class CallFailed(Exception):
    """Any other API error or timeout."""


@dataclass(frozen=True)
class Request:
    system: str
    document: str
    task: str
    effort: str = "low"
    max_output_tokens: int = 3000
    cache_key: str | None = None  # same for every call on one document: routes them to one cache


@dataclass
class Response:
    text: str
    truncated: bool  # hit max output tokens
    usage: Usage


class LLMClient(Protocol):
    async def complete(self, request: Request, on_text: Callable[[str], None]) -> Response:
        """Stream the answer. Call `on_text` with each piece as it arrives."""
        ...


class OpenAIClient:
    """Streams from the OpenAI Chat Completions API."""

    def __init__(self, model: str | None = None, timeout: float = 90.0, **client_kwargs) -> None:
        import openai

        self._openai = openai
        self.model = model or os.environ.get("FACT_EXTRACTOR_MODEL", "gpt-6-luna")
        self.client = openai.AsyncOpenAI(timeout=timeout, max_retries=0, **client_kwargs)

    async def complete(self, request: Request, on_text: Callable[[str], None]) -> Response:
        openai = self._openai
        parts: list[str] = []
        usage = Usage()
        finish = None
        try:
            stream = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": request.system},
                    {"role": "user", "content": request.document},
                    {"role": "user", "content": request.task},
                ],
                reasoning_effort=request.effort,
                max_completion_tokens=request.max_output_tokens,
                stream=True,
                stream_options={"include_usage": True},
                **({"prompt_cache_key": request.cache_key} if request.cache_key else {}),
            )
            async for chunk in stream:
                if chunk.usage:
                    u = chunk.usage
                    details = getattr(u, "prompt_tokens_details", None)
                    usage = Usage(
                        input_tokens=u.prompt_tokens,
                        cached_tokens=(getattr(details, "cached_tokens", 0) or 0) if details else 0,
                        output_tokens=u.completion_tokens,
                    )
                for choice in chunk.choices:
                    if choice.delta and choice.delta.content:
                        parts.append(choice.delta.content)
                        on_text(choice.delta.content)
                    if choice.finish_reason:
                        finish = choice.finish_reason
        except openai.RateLimitError as e:
            raise RateLimited(str(e)) from e
        except (openai.APIError, TimeoutError) as e:
            raise CallFailed(str(e)) from e
        return Response("".join(parts), finish == "length", usage)
