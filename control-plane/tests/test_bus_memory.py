"""Unit tests for InMemoryEventBus — the EventBus fake used across the suite.

Covers TRZ-P1-03 DoD: crashed-consumer reclaim (XAUTOCLAIM's job in the
real bus, exercised here via an injectable clock) and DLQ routing on a
poison event.
"""

from __future__ import annotations

from trazo_server.bus import InMemoryEventBus


class _FakeClock:
    """Manually-advanced clock so idle-time-based reclaim is deterministic."""

    def __init__(self) -> None:
        self._now = 0.0

    def __call__(self) -> float:
        return self._now

    def advance(self, *, seconds: float) -> None:
        self._now += seconds


async def test_bus__publish_and_read_group_delivers_message() -> None:
    bus = InMemoryEventBus()
    await bus.ensure_group("events", "workers")
    await bus.publish("events", {"event": "payload-1"})

    messages = await bus.read_group(
        "events", "workers", "consumer-a", count=10, block_ms=0
    )

    assert len(messages) == 1
    assert messages[0].fields == {"event": "payload-1"}


async def test_bus__ack_clears_pending_so_reclaim_skips_it() -> None:
    clock = _FakeClock()
    bus = InMemoryEventBus(clock=clock)
    await bus.ensure_group("events", "workers")
    await bus.publish("events", {"event": "payload-1"})
    [message] = await bus.read_group(
        "events", "workers", "consumer-a", count=10, block_ms=0
    )

    await bus.ack("events", "workers", message.message_id)
    clock.advance(seconds=60)
    reclaimed = await bus.reclaim_stale(
        "events", "workers", "consumer-b", min_idle_ms=1000, count=10
    )

    assert reclaimed == []


async def test_bus__crashed_consumer_message_is_reclaimed_by_another_consumer() -> None:
    """consumer-a reads a message and dies before acking it — reclaim_stale
    (backed by XAUTOCLAIM in the real bus) must hand it to consumer-b."""
    clock = _FakeClock()
    bus = InMemoryEventBus(clock=clock)
    await bus.ensure_group("events", "workers")
    await bus.publish("events", {"event": "payload-1"})
    [delivered] = await bus.read_group(
        "events", "workers", "consumer-a", count=10, block_ms=0
    )

    clock.advance(seconds=60)  # consumer-a is gone; message sits idle
    reclaimed = await bus.reclaim_stale(
        "events", "workers", "consumer-b", min_idle_ms=30_000, count=10
    )

    assert len(reclaimed) == 1
    assert reclaimed[0].message_id == delivered.message_id
    assert reclaimed[0].fields == {"event": "payload-1"}

    # consumer-b can now ack it; a second reclaim finds nothing left.
    await bus.ack("events", "workers", reclaimed[0].message_id)
    clock.advance(seconds=60)
    still_pending = await bus.reclaim_stale(
        "events", "workers", "consumer-c", min_idle_ms=1000, count=10
    )
    assert still_pending == []


async def test_bus__reclaim_respects_min_idle_threshold() -> None:
    clock = _FakeClock()
    bus = InMemoryEventBus(clock=clock)
    await bus.ensure_group("events", "workers")
    await bus.publish("events", {"event": "payload-1"})
    await bus.read_group("events", "workers", "consumer-a", count=10, block_ms=0)

    clock.advance(seconds=1)  # not idle long enough yet
    reclaimed = await bus.reclaim_stale(
        "events", "workers", "consumer-b", min_idle_ms=30_000, count=10
    )

    assert reclaimed == []


async def test_bus__dead_letter_moves_poison_message_off_source_stream() -> None:
    bus = InMemoryEventBus()
    await bus.ensure_group("events", "workers")
    await bus.publish("events", {"event": "not-valid-json"})
    [message] = await bus.read_group(
        "events", "workers", "consumer-a", count=10, block_ms=0
    )

    await bus.dead_letter(
        "events", "workers", message, reason="schema validation failed"
    )

    assert await bus.dlq_depth("events") == 1
    # acked off the source stream: a reclaim finds nothing left pending
    reclaimed = await bus.reclaim_stale(
        "events", "workers", "consumer-b", min_idle_ms=0, count=10
    )
    assert reclaimed == []


async def test_bus__lag_reports_undelivered_message_count() -> None:
    bus = InMemoryEventBus()
    await bus.ensure_group("events", "workers")
    assert await bus.lag("events", "workers") == 0

    await bus.publish("events", {"event": "a"})
    await bus.publish("events", {"event": "b"})
    assert await bus.lag("events", "workers") == 2

    await bus.read_group("events", "workers", "consumer-a", count=1, block_ms=0)
    assert await bus.lag("events", "workers") == 1
