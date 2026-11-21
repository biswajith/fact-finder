"""The chat session log: what happened in every turn, for review and for measuring cost.

One folder per chat session, `<run>/workspace/chat/<session id>/`, holds `session.json` and an
append-only `events.jsonl`. A session runs from the first message to the next "clear chat". Every
event carries the session id, the turn id (one per customer message) and a sequence number:

    user_message     the customer's text
    route            the planning mode chosen, by what (router, forced, fallback), with its Decisions call
    feedback         the judge's verdict on the customer's reply to a plan, with its Decisions call
    plan             the plan shown or carried out (steps or the one-line text) and its status
    llm_call         one chat-model call: purpose, round, tools offered and allowed, the tool calls it
                     asked for (arguments clipped), tokens (input, cached, output) and seconds
    tool             one tool run: name, arguments, ok, a short summary, seconds
    assistant_message  the reply's text
    turn_end         totals for the turn (calls, tokens, seconds) and any error

Writing the log never stops the chat: a failed write is counted, not raised. No FastAPI import here.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from .workspace import Workspace, new_id, now


@dataclass
class CallUsage:
    """Yielded by a chat model as the last item of a stream when the API reported token usage."""

    input_tokens: int | None = None
    cached_tokens: int | None = None
    output_tokens: int | None = None
    model: str = ""


class TurnLog:
    """The events of one customer message."""

    def __init__(self, ws: Workspace, session_id: str) -> None:
        self.ws = ws
        self.session_id = session_id
        self.turn_id = new_id("t_", 10)
        self.started = time.monotonic()
        self.seq = 0
        self.totals: dict[str, float] = {}
        self.write_errors = 0

    def _add(self, key: str, value: float) -> None:
        self.totals[key] = self.totals.get(key, 0) + value

    def log(self, event: str, **fields: Any) -> None:
        self.seq += 1
        entry = {"at": now(), "session_id": self.session_id, "turn_id": self.turn_id, "seq": self.seq,
                 "event": event, **fields}
        try:
            self.ws.append_chat_events(self.session_id, [entry])
        except Exception:  # the log must never break the chat
            self.write_errors += 1

    def llm_call(self, *, purpose: str, round_no: int | None, messages: int, tools_offered: int, tools_allowed: bool,
                 tool_calls: list[dict], text_chars: int, seconds: float, usage: CallUsage | None,
                 error: str | None = None) -> None:
        tokens = {}
        if usage is not None:
            tokens = {"input_tokens": usage.input_tokens, "cached_tokens": usage.cached_tokens,
                      "output_tokens": usage.output_tokens}
            for k, v in tokens.items():
                self._add(k, v or 0)
        self._add("llm_calls", 1)
        self._add("llm_seconds", seconds)
        fields: dict[str, Any] = {"purpose": purpose, "round": round_no, "messages": messages,
                                  "tools_offered": tools_offered, "tools_allowed": tools_allowed,
                                  "tool_calls": tool_calls, "text_chars": text_chars, "seconds": round(seconds, 3),
                                  **tokens}
        if usage is not None and usage.model:
            fields["model"] = usage.model
        if error:
            fields["error"] = error
        self.log("llm_call", **fields)

    def decisions_call(self, call: dict | None) -> dict | None:
        """Count a Decisions API call (`call` as the router or judge reported it) and return it for the event."""
        if not call:
            return None
        self._add("decisions_calls", 1)
        self._add("decisions_input_tokens", call.get("input_tokens") or 0)
        self._add("decisions_seconds", call.get("seconds") or 0)
        return call

    def tool(self, *, name: str, round_no: int, args: Any, ok: bool, summary: str, seconds: float) -> None:
        self._add("tool_calls", 1)
        self.log("tool", name=name, round=round_no, args=args, ok=ok, summary=summary, seconds=round(seconds, 3))

    def end(self, error: str | None) -> None:
        totals = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in self.totals.items()}
        totals["seconds"] = round(time.monotonic() - self.started, 3)
        fields: dict[str, Any] = {"totals": totals}
        if error:
            fields["error"] = error
        if self.write_errors:
            fields["write_errors"] = self.write_errors
        self.log("turn_end", **fields)
