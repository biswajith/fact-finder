"""Canonical numbers, dates and times for the number check (spec 7, REVIEW.md, "Spec departures" item 1).

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
# A date written without its year, as notes and calls write them: "5/10", "7/24", "September 16th",
# "16 Sept". Read in a source only (generous), as "md:MM-DD": a fact's full date with the same month
# and day rests on it, since the year comes from the context the writer knew.
_MONTH_DAY_PATTERNS = [
    re.compile(r"(?<![\d/.])(?P<m>\d{1,2})/(?P<day>\d{1,2})(?![\d/])"),
    re.compile(rf"\b{_MON}\s+{_DAY}\b(?!,?\s*\d)", re.I),
    re.compile(rf"\b{_DAY}(?:\s+of)?\s+{_MON}\b(?!,?\s*\d)", re.I),
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


_TENS = {"twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"}
_BIG = {"thousand": 1000, "million": 1_000_000, "billion": 1_000_000_000}


def _spelled(text: str) -> set[str]:
    """Numbers written out in words, read whole: "ninety-five thousand" -> 95000,
    "two hundred and fifty" -> 250, "a million" -> 1000000. Only runs of more than one
    word are read here; single number words are handled on their own."""
    toks = [(m.group(), m.start(), m.end()) for m in re.finditer(r"[a-z]+", text.lower())]
    out: set[str] = set()
    run: list[str] = []

    def close() -> None:
        while run and run[-1] in ("and", "a"):
            run.pop()
        if len(run) > 1:
            total = cur = 0
            for w in run:
                if w == "a":
                    cur = 1
                elif w == "hundred":
                    cur = (cur or 1) * 100
                elif w in _BIG:
                    total += (cur or 1) * _BIG[w]
                    cur = 0
                elif w != "and":
                    cur += _WORDS[w]
            out.add(str(total + cur))
        run.clear()

    for i, (w, start, _end) in enumerate(toks):
        nxt = toks[i + 1][0] if i + 1 < len(toks) else ""
        joined = bool(run) and re.fullmatch(r"[\s-]+", text[toks[i - 1][2]:start] or "x") is not None
        prev = run[-1] if run and joined else None
        if w == "a":
            ok_here = nxt in ("hundred", *_BIG)
        elif w == "and":
            ok_here = prev in ("hundred", *_BIG) and nxt in _WORDS and _WORDS[nxt] < 100
        elif w == "hundred" or w in _BIG:
            ok_here = True
        elif w in _WORDS and _WORDS[w] < 100 and w not in ("first", "second", "third", "fourth", "fifth"):
            # a unit after a tens word ("ninety-five"); otherwise a number word starts a new run
            ok_here = True
            if prev is not None and prev not in ("hundred", "and", *_BIG) and not (prev in _TENS and 0 < _WORDS[w] < 10):
                close()
                prev = None
        else:
            close()
            continue
        if not ok_here:
            close()
            continue
        if prev is None and run:
            close()
        run.append(w)
    close()
    return out


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
    if generous:
        for pat in _MONTH_DAY_PATTERNS:
            for m in pat.finditer(text):
                if not free(m):
                    continue
                g = m.groupdict()
                month = int(g["m"]) if g.get("m") else _MONTHS[g["mon"].lower()]
                day = int(g["day"])
                if 1 <= month <= 12 and 1 <= day <= 31:
                    out.update({f"md:{month:02d}-{day:02d}", str(month), str(day)})
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
        out |= _spelled(text)
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
    return {v for v in values(fact) - have if not (v.startswith("date:") and "md:" + v[10:] in have)}


_STOP = set(
    "a an the of to for and or in on by with at as be is are will shall must may any all its it this that "
    "from each per not no than into their there these those which who whom within".split()
)


def words(text: str) -> list[str]:
    """Lower-case words and numbers, in order."""
    return re.findall(r"[a-z0-9]+", text.lower())
