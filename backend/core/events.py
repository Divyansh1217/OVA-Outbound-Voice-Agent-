"""In-process event bus for SSE live updates on a per-call basis."""

from __future__ import annotations

import asyncio
import json
from typing import Any

SubscriberQueue = asyncio.Queue[dict[str, Any]]


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, set[SubscriberQueue]] = {}

    def subscribe(self, call_id: str) -> SubscriberQueue:
        q: SubscriberQueue = asyncio.Queue()
        self._subs.setdefault(call_id, set()).add(q)
        return q

    def unsubscribe(self, call_id: str, q: SubscriberQueue) -> None:
        subs = self._subs.get(call_id)
        if subs:
            subs.discard(q)
            if not subs:
                self._subs.pop(call_id, None)

    def publish(self, call_id: str, event: dict[str, Any]) -> None:
        subs = self._subs.get(call_id)
        if not subs:
            return
        for q in list(subs):
            try:
                q.put_nowait(event)
            except Exception:
                pass


bus = EventBus()


def sse_frame(payload: dict[str, Any]) -> str:
    """Serialize an event dict into an SSE data frame."""
    return f"data: {json.dumps(payload)}\n\n"