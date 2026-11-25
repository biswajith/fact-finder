"""Current values: one value per key, settled in code from the facts that state it. No model call.

A fact that states a value carries a key (`thing.attribute`) and the value alone, both given by the
LABEL call (units.py) and voted like the label. The same value is stated in several places and
documents, sometimes differently. Here every key gets one current value:

1. Same or different (`same`). Two values of one key are the same when they clean to the same text,
   when both hold figures and one's figures are all in the other (2024-06-10 is a shorter
   2024-06-10 14:00 ET), when their largest numbers are equal (95k, 95,000), or when one is given
   as about a number within 2% of the other's.
2. Which stands (`settle`). The source level ranks them (bid.level_of: 1 a buyer document, 2 the
   buyer speaking on a call, 3 our side on a call, 4 the team's notes); inside a level the later
   document wins.
   - A value with a calendar date replaces an estimate or a placeholder of the same key, whatever
     the levels: "week of 2024-09-16" replaces "TBD".
   - The buyer against the buyer (levels 1 and 2 holding different figures) needs a person. The
     document's value stands until then.
   - Values without figures that differ (several contacts) are not rivals: they are listed.

The facts are not changed: each stays a record of what its source said. A reader who needs the value
reads the key; a change to the value is one write to the key (workspace.py, `set_value`).
"""

from __future__ import annotations

import re

from .normalize import values as _values

LEVEL = {1: "the buyer's document", 2: "the buyer on a call", 3: "our side on a call", 4: "the team's notes"}
OPEN = ("needs_review",)  # statuses a person must look at

_MONTH = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b", re.I)
_ABOUT = re.compile(r"\b(about|around|roughly|approximately|approx|nearly|some)\b|~", re.I)
_DATE_KEYS = ("date", "due", "start", "deadline")


def clean(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9$%.]+", " ", str(text).lower()).split()).strip(" .")


def figures(text: str) -> set[str]:
    """What a value holds, for comparing two values of one key. A date, a day of a month or a time
    stands as itself (a date also as its day and its year); the loose numbers they are made of are
    dropped. Without any of those, every number stands."""
    got = set(_values(text, generous=True))
    typed = {v for v in got if ":" in v}
    if not typed:
        return got
    out = set(typed)
    for v in typed:
        if v.startswith("date:"):
            out |= {"md:" + v[10:], v[5:9]}
    return out


def same(a: str, b: str) -> bool:
    """Whether two values of one key say the same thing (see the module text)."""
    if clean(a) == clean(b):
        return True
    fa, fb = figures(a), figures(b)
    if not fa or not fb:
        return False
    if fa <= fb or fb <= fa:
        return True
    if any(":" in v for v in fa | fb):
        return False
    try:
        ma, mb = max(float(v) for v in fa), max(float(v) for v in fb)
    except ValueError:
        return False
    return ma == mb or (bool(_ABOUT.search(a) or _ABOUT.search(b)) and abs(ma - mb) <= 0.02 * max(ma, mb))


def dated(text: str) -> bool:
    """The value names a day or a month, not only a span of time or a placeholder."""
    return any(v.startswith(("date:", "md:")) for v in _values(text, generous=True)) or bool(_MONTH.search(text))


def _newest_first(date: str) -> str:
    return "".join(chr(255 - ord(ch)) for ch in date or "")


def title(part: str) -> str:
    return part.replace("-", " ").replace(".", " ").capitalize()


def settle(key: str, claims: list[dict]) -> dict:
    """One key's current value from its claims: {value, fact_id, level, issued, tentative}.

    Returns {key, thing, attribute, value, status, reason, fact_ids, other}. `status` is "" when the
    sources agree, "auto_resolved" when the ranking or a stated date chose, "needs_review" when a
    person must, "tentative" when every source gives the value as not final. `other` lists the values
    that do not stand, each with its facts and `why`: "outranked", "open" (the rival a person must
    choose against), "placeholder" or "listed"."""
    groups: list[dict] = []
    # The fullest values first, so a bare date joins the dated time it agrees with, never the other way round.
    for c in sorted(claims, key=lambda c: (-len(figures(c["value"])), c["level"])):
        for g in groups:
            if same(c["value"], g["claims"][0]["value"]):
                g["claims"].append(c)
                break
        else:
            groups.append({"claims": [c]})
    for g in groups:
        rank = lambda c: (c["level"], _newest_first(c["issued"]))  # noqa: E731
        g["rank"] = min(rank(c) for c in g["claims"])
        g["level"] = g["rank"][0]
        g["value"] = min(g["claims"], key=lambda c: (rank(c), -len(c["value"])))["value"]
        g["fact_ids"] = list(dict.fromkeys(c["fact_id"] for c in g["claims"]))
        g["dated"] = any(dated(c["value"]) for c in g["claims"])
        g["figures"] = bool(figures(g["value"]))
    groups.sort(key=lambda g: g["rank"])
    attribute = key.rsplit(".", 1)[-1]
    specific = [g for g in groups if g["dated"]]
    placeholders = [g for g in groups if not g["dated"]] if specific and attribute.endswith(_DATE_KEYS) else []
    rivals = [g for g in groups if g not in placeholders]
    win = rivals[0]
    listed = [g for g in rivals[1:] if not (g["figures"] or win["figures"])]
    rest = [g for g in rivals[1:] if g not in listed]
    status, reason, why = "", "", "outranked"
    if rest:
        if rest[0]["level"] == win["level"]:
            status, why = "needs_review", "open"
            reason = f"Two statements from {LEVEL.get(win['level'], 'one source')} disagree: a person must choose."
        elif {win["level"], rest[0]["level"]} == {1, 2}:
            status, why = "needs_review", "open"
            reason = ("The buyer said something different on a call than its document says. The document's value "
                      "stands until a person decides.")
        else:
            status = "auto_resolved"
            reason = f"{LEVEL.get(win['level'], 'The stronger source').capitalize()} outranks {LEVEL.get(rest[0]['level'], 'the other')}."
    elif placeholders:
        status = "auto_resolved"
        reason = f"A stated date replaces the estimate or placeholder ({placeholders[0]['value']})."
    elif all(c.get("tentative") for g in [win] for c in g["claims"]):
        status, reason = "tentative", "Every source gives it as not final."
    other = ([{"value": g["value"], "fact_ids": g["fact_ids"], "why": why} for g in rest]
             + [{"value": g["value"], "fact_ids": g["fact_ids"], "why": "placeholder"} for g in placeholders]
             + [{"value": g["value"], "fact_ids": g["fact_ids"], "why": "listed"} for g in listed])
    return {"key": key, "thing": title(key.rsplit(".", 1)[0]), "attribute": title(attribute), "value": win["value"],
            "status": status, "reason": reason, "fact_ids": win["fact_ids"], "other": other}


def values(facts: list[dict], issued: dict[str, str] | None = None) -> list[dict]:
    """The current value of every key the facts carry, in key order. `facts` are fact records (those
    deleted or replaced by a later document give no claim); `issued` maps a doc_id to its issue date."""
    issued = issued or {}
    claims: dict[str, list[dict]] = {}
    for f in facts:
        if not f.get("key") or not f.get("value") or f.get("deleted") or "replaced" in (f.get("flags") or []):
            continue
        claims.setdefault(f["key"], []).append({
            "value": f["value"], "fact_id": f["fact_id"], "level": int(f.get("level") or 1),
            "issued": issued.get(f.get("doc_id", ""), ""), "tentative": "tentative" in (f.get("flags") or []),
        })
    return [settle(k, claims[k]) for k in sorted(claims)]
