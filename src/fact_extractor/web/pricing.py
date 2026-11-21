"""Model prices, for the cost estimates in the chat session log (chatlog.py).

US dollars per 1M tokens, standard tier, read on 2026-11-21 from
https://developers.openai.com/api/docs/models/gpt-6-luna and https://openai.com/index/decisions-api/.
Change them here when the price pages change; logged costs keep the price they were logged at.

Estimates, not invoices: uncached input is priced at the input rate, although the API may bill part
of it as a cache write (1.25x input); the Decisions usage report gives no cached count, so all
Decisions input is priced as uncached. Both make small differences at chat sizes.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Price:
    input: float
    cached_input: float
    output: float
    long_context_over: int | None = None  # above this many input tokens the whole request costs more
    long_input_factor: float = 1.0
    long_output_factor: float = 1.0


CHAT: dict[str, Price] = {
    # Prompts over 272K input tokens: 2x input and cache rates, 1.5x output, for the full request.
    "gpt-6-luna": Price(0.10, 0.01, 0.50, long_context_over=272_000, long_input_factor=2.0, long_output_factor=1.5),
}

# The Decisions API bills input tokens only; there are no output-token charges.
DECISIONS: dict[str, Price] = {
    "gpt-6-luna": Price(0.10, 0.01, 0.0),
}


def cost(prices: dict[str, Price], model: str, input_tokens: int | None, cached_tokens: int | None = 0,
         output_tokens: int | None = 0) -> float | None:
    """Estimated dollars for one call, or None for a model with no known price or no token counts."""
    p = prices.get(model)
    if p is None or input_tokens is None:
        return None
    cached = min(cached_tokens or 0, input_tokens)
    fi = fo = 1.0
    if p.long_context_over is not None and input_tokens > p.long_context_over:
        fi, fo = p.long_input_factor, p.long_output_factor
    return ((input_tokens - cached) * p.input * fi + cached * p.cached_input * fi
            + (output_tokens or 0) * p.output * fo) / 1_000_000


def fill_costs(events: list[dict]) -> list[dict]:
    """Price session log events written before costs were logged, from the model and token counts they
    kept, at today's prices. Events that already have a cost keep it. A turn_end whose cost is added
    here is marked `cost_added_later`."""
    llm: dict[str, float] = {}
    dec: dict[str, float] = {}
    priced: set[str] = set()
    out = []
    for e in events:
        e = dict(e)
        turn = e.get("turn_id", "")
        if e.get("event") == "llm_call":
            usd = e.get("cost_usd")
            if usd is None:
                usd = cost(CHAT, e.get("model") or "", e.get("input_tokens"), e.get("cached_tokens"), e.get("output_tokens"))
                if usd is not None:
                    e["cost_usd"] = round(usd, 8)
            if usd is not None:
                llm[turn] = llm.get(turn, 0) + usd
                priced.add(turn)
        call = e.get("call")
        if isinstance(call, dict):
            usd = call.get("cost_usd")
            if usd is None:
                usd = cost(DECISIONS, call.get("model") or "", call.get("input_tokens"))
                if usd is not None:
                    e["call"] = {**call, "cost_usd": round(usd, 8)}
            if usd is not None:
                dec[turn] = dec.get(turn, 0) + usd
                priced.add(turn)
        if e.get("event") == "turn_end" and isinstance(e.get("totals"), dict) and "cost_usd" not in e["totals"] and turn in priced:
            a, b = llm.get(turn, 0.0), dec.get(turn, 0.0)
            e["totals"] = {**e["totals"], "llm_cost_usd": round(a, 8), "decisions_cost_usd": round(b, 8),
                           "cost_usd": round(a + b, 8)}
            e["cost_added_later"] = True
        out.append(e)
    return out
