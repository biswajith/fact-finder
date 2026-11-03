"""RFP fact extraction: whole tagged document, parallel calls, ID citations."""

from .models import Anchor, Fact, TaggedDocument
from .pipeline import Config, RecordingDecisions, RunResult, extract
from .store import InMemoryFactStore
from .tagging import Heading, Page, Paragraph, Span, Table, tag_pages

__all__ = [
    "Anchor", "Config", "Fact", "Heading", "InMemoryFactStore", "Page", "Paragraph",
    "RecordingDecisions", "RunResult", "Span", "Table", "TaggedDocument", "extract", "tag_pages",
]
