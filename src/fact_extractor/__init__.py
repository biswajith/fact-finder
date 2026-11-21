"""RFP fact extraction: whole tagged document, parallel calls, ID citations."""

from .api import LabelledFact, LabelResult, SourceUnit, document_from_units, label_units
from .models import Anchor, Fact, TaggedDocument
from .pipeline import Config, RecordingDecisions, RunResult, extract
from .store import InMemoryFactStore
from .tagging import Heading, Page, Paragraph, Span, Table, tag_pages

__all__ = [
    "Anchor", "Config", "Fact", "Heading", "InMemoryFactStore", "LabelResult", "LabelledFact", "Page",
    "Paragraph", "RecordingDecisions", "RunResult", "SourceUnit", "Span", "Table", "TaggedDocument",
    "document_from_units", "extract", "label_units", "tag_pages",
]
