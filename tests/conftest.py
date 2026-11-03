from __future__ import annotations

import asyncio
from typing import Callable

import pytest

from fact_extractor.llm import Request, Response
from fact_extractor.models import Usage
from fact_extractor.tagging import Heading, Page, Paragraph, Table, tag_pages


def sample_pages() -> list[Page]:
    return [
        Page(1, "i", [
            Heading("1. Introduction"),
            Paragraph.of(
                "The City of Springfield seeks proposals for a records management system. "
                "Questions must be sent by email to jane.doe@springfield.gov."
            ),
            Heading("2. Schedule"),
            Paragraph.of(
                "Proposals are due March 3, 2027 at 5:00 PM Eastern. "
                "A pre-bid meeting will be held on February 10, 2027."
            ),
        ]),
        Page(2, "1", [
            Heading("3. Requirements"),
            Paragraph.of(
                "The system shall support 500 concurrent users. The vendor must provide 24/7 support. "
                "Data must be retained for 7 years."
            ),
            Table(["Item", "Requirement", "Mandatory"], [["Support hours", "24/7", "Yes"], ["Uptime", "99.9%", "Yes"]]),
        ]),
        Page(3, "2", [
            Heading("4. Submission"),
            Paragraph.of("Proposals shall not exceed 50 pages. Proposals are due March 5, 2027."),
        ]),
    ]


@pytest.fixture
def doc():
    return tag_pages("rfp-001", sample_pages())


Handler = Callable[[Request], "str | Exception"]


class ScriptedClient:
    """Fake model: a handler maps each request to output text or an exception."""

    def __init__(self, handler: Handler, chunk: int = 7, truncate_at: int | None = None) -> None:
        self.handler = handler
        self.chunk = chunk
        self.truncate_at = truncate_at
        self.requests: list[Request] = []
        self.seen_prefixes: set[tuple[str, str]] = set()

    async def complete(self, request: Request, on_text) -> Response:
        self.requests.append(request)
        out = self.handler(request)
        if isinstance(out, Exception):
            raise out
        cached = (request.system, request.document) in self.seen_prefixes
        self.seen_prefixes.add((request.system, request.document))
        text = out
        for i in range(0, len(text), self.chunk):
            await asyncio.sleep(0)
            on_text(text[i : i + self.chunk])
        n_in = len(request.system + request.document + request.task) // 4
        usage = Usage(n_in, len(request.system + request.document) // 4 if cached else 0, len(text) // 4)
        return Response(text, False, usage)


def task_name(req: Request) -> str:
    return req.task.split("\n", 1)[0].removeprefix("TASK ").strip()
