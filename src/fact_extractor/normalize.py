"""Canonical numbers, dates and times for the number check (spec 7, REVIEW.md item 3).

`values(text)` returns a set of canonical tokens. A fact passes when every
token of the fact is in the token set of its cited text. The fact is parsed
strictly (dates consume their parts); the source is parsed generously (a date
also yields its year, day and month numbers, and number words count).
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("january", "jan"), ("february", "feb"), ("march", "mar"), ("april", "apr"),
            ("may",), ("june", "jun"), ("july", "jul"), ("august", "aug"),
            ("september", "sep", "sept"), ("october", "oct"), ("november", "nov"), ("december", "dec"),
        ],
        start=1,
    )
    for m in names
}
_MON = r"(?P<mon>" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?"
_DAY = r"(?P<day>\d{1,2})(?:st|nd|rd|th)?"
_YEAR = r"(?P<year>\d{4})"

_DATE_PATTERNS = [
    re.compile(r"\b(?P<year>\d{4})-(?P<m>\d{1,2})-(?P<day>\d{1,2})\b"),
    re.compile(rf"\b{_MON}\s+{_DAY},?\s+{_YEAR}\b", re.I),
    re.compile(rf"\b{_DAY}(?:\s+of)?\s+{_MON},?\s+{_YEAR}\b", re.I),
    re.compile(r"\b(?P<m>\d{1,2})/(?P<day>\d{1,2})/(?P<year>\d{4})\b"),  # US order
]
_TIME = re.compile(
    r"\b(?P<h>\d{1,2})(?::(?P<min>\d{2}))?\s*(?P<ap>a\.?\s?m\.?|p\.?\s?m\.?)(?![a-z])"
    r"|\b(?P<h24>[01]?\d|2[0-3]):(?P<min24>[0-5]\d)\b",
    re.I,
)
_SPECIAL_TIME = re.compile(r"\b(noon|midnight)\b", re.I)
_SCALE = {"thousand": 3, "k": 3, "million": 6, "m": 6, "mm": 6, "billion": 9, "bn": 9, "b": 9}
_NUMBER = re.compile(
    r"(?<![\w.])(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)+|\d+)"
    r"(?:st|nd|rd|th)?"
    r"(?:\s*(?P<scale>thousand|million|billion)\b|(?P<sscale>mm|bn|k|m|b)\b)?",
    re.I,
)
_WORDS = {
    w: i
    for i, w in enumerate(
        "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
        "fifteen sixteen seventeen eighteen nineteen twenty".split()
    )
} | {"thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
     "hundred": 100, "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}


def _num(s: str, scale: str | None = None) -> str | None:
    s = s.replace(",", "")
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None
    if scale:
        d = d.scaleb(_SCALE[scale.lower()])
    d = d.normalize()
    return format(d, "f")


def values(text: str, *, generous: bool = False) -> set[str]:
    out: set[str] = set()
    taken = [False] * len(text)

    def take(m: re.Match) -> None:
        for i in range(m.start(), m.end()):
            taken[i] = True

    def free(m: re.Match) -> bool:
        return not any(taken[m.start() : m.end()])

    for pat in _DATE_PATTERNS:
        for m in pat.finditer(text):
            if not free(m):
                continue
            g = m.groupdict()
            month = int(g["m"]) if g.get("m") else _MONTHS[g["mon"].lower()]
            day, year = int(g["day"]), int(g["year"])
            if not (1 <= month <= 12 and 1 <= day <= 31):
                continue
            out.add(f"date:{year:04d}-{month:02d}-{day:02d}")
            if generous:
                out.update({str(year), str(day), str(month)})
            take(m)

    for m in _TIME.finditer(text):
        if not free(m):
            continue
        if m.group("h24") is not None:
            h, mi = int(m.group("h24")), int(m.group("min24"))
            # "4.2" or ratios like "3:1" are not times; require a 2-digit minute.
        else:
            h, mi = int(m.group("h")), int(m.group("min") or 0)
            if not 1 <= h <= 12:
                continue
            pm = m.group("ap").lower().startswith("p")
            h = (h % 12) + (12 if pm else 0)
        out.add(f"time:{h:02d}:{mi:02d}")
        if generous:
            out.update({str(int(m.group("h") or m.group("h24"))), str(mi)})
        take(m)
    for m in _SPECIAL_TIME.finditer(text):
        out.add("time:12:00" if m.group(1).lower() == "noon" else "time:00:00")

    for m in _NUMBER.finditer(text):
        if not free(m):
            continue
        scale = m.group("scale") or m.group("sscale")
        n = _num(m.group("num"), scale)
        if n is not None:
            out.add(n)
            if generous and scale:
                out.add(_num(m.group("num")) or n)
        take(m)

    if generous:
        for w in re.findall(r"[a-z]+", text.lower()):
            if w in _WORDS:
                out.add(str(_WORDS[w]))
        # "noon"/"midnight" may also be written as 12:00 in a fact
    return out


# PDF text often loses the spaces between words ("afterMay 24", "May24 2024 at2pmET",
# "Anestimated30daysafter", form blanks like "___2."), so the word boundaries the
# patterns need are missing. Re-insert a space where a letter or underscore runs into
# a digit, or a lowercase letter into an uppercase one. A digit running into a letter
# is left alone so "10k" and "1st" keep their meaning.
_GLUED = re.compile(r"(?<=[A-Za-z_])(?=\d)|(?<=[a-z])(?=[A-Z])")


def unglue(text: str) -> str:
    return _GLUED.sub(" ", text)


def missing_values(fact: str, sources: list[str]) -> set[str]:
    """Tokens in `fact` not supported by any of the cited `sources`.

    Sources are read both as written and with glued words split apart; the fact is
    parsed as written. Splitting can only add source values, so it never makes a
    fact fail that passed before.
    """
    have: set[str] = set()
    for s in sources:
        have |= values(s, generous=True)
        split = unglue(s)
        if split != s:
            have |= values(split, generous=True)
    return values(fact) - have
