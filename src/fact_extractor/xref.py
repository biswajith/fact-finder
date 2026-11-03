"""Cross-reference check in code (REVIEW.md, "Cross-reference check").

Finds references such as "Article 17 (Intellectual Property)" or "Schedule C"
in the text and looks them up in the document's own headings. Writes a Q fact
when the target is blank, has a different title, or (for articles) does not
exist. No model call: these mismatches sit between one sentence and a heading
pages away, which the model's contradiction check does not see.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .merge import similarity
from .models import Fact, TaggedDocument

KINDS = ("article", "section", "schedule", "attachment", "exhibit", "appendix")
_NUM = r"(\d+(?:\.\d+)*|[A-Z])"
_HEADING = re.compile(rf"^(?P<kind>{'|'.join(KINDS)})\s+(?P<num>{_NUM})\b\s*[-–—:.]?\s*(?P<title>.*)$", re.I)
_REF = re.compile(
    rf"\b(?P<kind>{'|'.join(KINDS)})\s+(?P<num>{_NUM})\b(?:\s*\((?P<title>[^()]{{3,80}})\))?",
    re.I,
)
# "Article 15 of the Executive Law", "Article 2 of Chapter 18": a reference into another document.
_EXTERNAL = re.compile(r"^\s*(?:of|under|to)\s+(?:the\s+)?(?!this\b)(?:[A-Z][\w.'’-]*\s*){1,6}", re.U)
_BLANK = re.compile(r"intentionally\s+(?:left\s+)?blank|\breserved\b|not\s+used", re.I)
# Missing targets are only reported for kinds numbered inside the document; attachments and
# exhibits are often separate files.
_CHECK_MISSING = {"article"}
TITLE_SIMILARITY = 0.5


@dataclass(frozen=True)
class _Target:
    id: str
    title: str


def _headings(doc: TaggedDocument) -> dict[tuple[str, str], _Target]:
    out: dict[tuple[str, str], _Target] = {}
    for a in doc.anchors.values():
        if a.kind != "heading":
            continue
        m = _HEADING.match(a.text)
        if m:
            key = (m.group("kind").lower(), m.group("num").upper())
            out.setdefault(key, _Target(a.id, m.group("title").strip()))
    return out


def check(doc: TaggedDocument) -> list[Fact]:
    targets = _headings(doc)
    kinds_present = {k for k, _ in targets}
    facts: list[Fact] = []
    seen: set[tuple[str, str, str]] = set()
    for a in doc.anchors.values():
        if a.kind == "heading":
            continue
        for m in _REF.finditer(a.text):
            kind, num, title = m.group("kind").lower(), m.group("num").upper(), (m.group("title") or "").strip()
            if _EXTERNAL.match(a.text[m.end() :]):
                continue
            if kind not in kinds_present:
                continue  # the document has no headings of this kind to check against
            ref = f"{kind.title()} {num}" + (f" ({title})" if title else "")
            key = (a.id, kind, num)
            if key in seen:
                continue
            seen.add(key)
            t = targets.get((kind, num))
            if t is None:
                if kind in _CHECK_MISSING:
                    facts.append(_q(f"Cross-reference to {ref}, but the document has no {kind.title()} {num}", [a.id]))
                continue
            if _BLANK.search(t.title):
                facts.append(_q(f"Cross-reference to {ref}, but {kind.title()} {num} is {t.title.lower()}", [a.id, t.id]))
            elif title and t.title and similarity(title, t.title) < TITLE_SIMILARITY:
                facts.append(
                    _q(f"Cross-reference to {ref}, but {kind.title()} {num} is titled {t.title.title()}", [a.id, t.id])
                )
    return facts


def _q(text: str, ids: list[str]) -> Fact:
    return Fact("Q", text, ids, "", "valid", "XREF")
