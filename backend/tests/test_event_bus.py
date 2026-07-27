"""Tests for the SSE event bus (subscribers must be hashable)."""
from __future__ import annotations

import asyncio

import pytest

from app.jobs.event_bus import EventBus


@pytest.mark.asyncio
async def test_subscribe_and_publish_roundtrip():
    bus = EventBus()
    sub = await bus.subscribe("run-1")
    await bus.publish("run-1", {"event": "snapshot", "status": "running_target"})
    evt = await asyncio.wait_for(sub.queue.get(), timeout=1.0)
    assert evt["event"] == "snapshot"
    assert evt["status"] == "running_target"


@pytest.mark.asyncio
async def test_subscription_is_hashable():
    """Regression: dataclass _Subscription must be usable in a set."""
    bus = EventBus()
    sub = await bus.subscribe("run-2")
    # The internal subscription set must contain the sub without TypeError.
    assert sub in bus._subs["run-2"]


@pytest.mark.asyncio
async def test_history_replay_on_subscribe():
    bus = EventBus()
    await bus.publish("run-3", {"event": "prompt", "n": 1})
    await bus.publish("run-3", {"event": "prompt", "n": 2})
    sub = await bus.subscribe("run-3")
    # History should be replayed immediately.
    evt1 = await asyncio.wait_for(sub.queue.get(), timeout=1.0)
    evt2 = await asyncio.wait_for(sub.queue.get(), timeout=1.0)
    assert evt1["n"] == 1
    assert evt2["n"] == 2


@pytest.mark.asyncio
async def test_unsubscribe_removes_sub():
    bus = EventBus()
    sub = await bus.subscribe("run-4")
    await bus.unsubscribe("run-4", sub)
    assert sub not in bus._subs.get("run-4", set())
