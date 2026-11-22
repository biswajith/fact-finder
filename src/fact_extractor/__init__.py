"""RFP fact extraction: label the units of a tagged document, cite them by ID."""

from .api import LabelledFact, LabelResult, SourceUnit, document_from_units, label_units
from .models import Anchor, TaggedDocument
from .tagging import Heading, Page, Paragraph, Span, Table, tag_pages

__all__ = [
    "Anchor", "Heading", "LabelResult", "LabelledFact", "Page", "Paragraph", "SourceUnit", "Span", "Table",
    "TaggedDocument", "document_from_units", "label_units", "tag_pages",
]
