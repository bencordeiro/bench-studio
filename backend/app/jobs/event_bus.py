"""In-process event bus for live progress (SSE / WebSocket).

The benchmark job publishes progress events; SSE subscribers receive them.
Events are also persisted to the run's summary so polling can recover state
after a browser reconnect.
"""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass(eq=False)
class _Subscription:
    """A single SSE subscriber. eq=False makes it hashable by identity (object id),
    which is what we need for set membership."""
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=100))


class EventBus:
    def __init__(self, history_size: int = 200) -> None:
        self._subs: dict[str, set[_Subscription]] = {}
        self._history: dict[str, deque[dict[str, Any]]] = {}
        self._history_size = history_size
        self._lock = asyncio.Lock()

    def _hist(self, run_id: str) -> deque:
        if run_id not in self._history:
            self._history[run_id] = deque(maxlen=self._history_size)
        return self._history[run_id]

    async def publish(self, run_id: str, event: dict[str, Any]) -> None:
        async with self._lock:
            self._hist(run_id).append(event)
            subs = list(self._subs.get(run_id, ()))
        for sub in subs:
            try:
                sub.queue.put_nowait(event)
            except asyncio.QueueFull:
                # Drop oldest to make room for live events.
                try:
                    sub.queue.get_nowait()
                    sub.queue.put_nowait(event)
                except Exception:
                    pass

    async def subscribe(self, run_id: str) -> _Subscription:
        async with self._lock:
            sub = _Subscription()
            self._subs.setdefault(run_id, set()).add(sub)
            # Replay recent history to this subscriber immediately.
            for evt in list(self._history.get(run_id, ())):
                try:
                    sub.queue.put_nowait(evt)
                except asyncio.QueueFull:
                    break
        return sub

    async def unsubscribe(self, run_id: str, sub: _Subscription) -> None:
        async with self._lock:
            self._subs.get(run_id, set()).discard(sub)

    def clear(self, run_id: str) -> None:
        self._history.pop(run_id, None)
        self._subs.pop(run_id, None)


bus = EventBus()
