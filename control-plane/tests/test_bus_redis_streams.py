"""Integration tests for RedisStreamsBus against a live Redis.

Skipped automatically when Redis isn't reachable (DEVELOPMENT_GUIDE.md:
these need `make up`). TRZ-P1-03's unit-test DoD is satisfied by
test_bus_memory.py; this file proves the real implementation honors the
same Protocol against actual Redis Streams semantics (XGROUP/XREADGROUP/
XACK/XAUTOCLAIM/DLQ).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from redis.asyncio import Redis

from trazo_server.bus import RedisStreamsBus
from trazo_server.config import Settings


@pytest.fixture
async def redis_client() -> AsyncIterator[Redis]:
    redis = Redis.from_url(Settings().redis_url, decode_responses=True)
    try:
        await redis.ping()
    except Exception:
        pytest.skip("Redis not reachable — run `make up` for integration coverage")
    yield redis
    await redis.aclose()


@pytest.fixture
def stream_name() -> str:
    # unique per test so parallel/repeated runs don't collide on shared Redis
    return f"test-events-{uuid.uuid4().hex[:8]}"


async def test_bus__publish_and_read_group_round_trips(
    redis_client: Redis, stream_name: str
) -> None:
    bus = RedisStreamsBus(redis_client)
    await bus.ensure_group(stream_name, "workers")
    await bus.publish(stream_name, {"event": "payload-1"})

    messages = await bus.read_group(
        stream_name, "workers", "consumer-a", count=10, block_ms=100
    )

    assert len(messages) == 1
    assert messages[0].fields == {"event": "payload-1"}
    await redis_client.delete(stream_name)


async def test_bus__ensure_group_is_idempotent(
    redis_client: Redis, stream_name: str
) -> None:
    bus = RedisStreamsBus(redis_client)
    await bus.ensure_group(stream_name, "workers")
    await bus.ensure_group(stream_name, "workers")  # must not raise BUSYGROUP
    await redis_client.delete(stream_name)


async def test_bus__crashed_consumer_message_is_reclaimed(
    redis_client: Redis, stream_name: str
) -> None:
    bus = RedisStreamsBus(redis_client)
    await bus.ensure_group(stream_name, "workers")
    await bus.publish(stream_name, {"event": "payload-1"})
    [delivered] = await bus.read_group(
        stream_name, "workers", "consumer-a", count=10, block_ms=100
    )

    # consumer-a "crashes" without acking; min_idle_ms=0 claims immediately.
    reclaimed = await bus.reclaim_stale(
        stream_name, "workers", "consumer-b", min_idle_ms=0, count=10
    )

    assert len(reclaimed) == 1
    assert reclaimed[0].message_id == delivered.message_id
    await bus.ack(stream_name, "workers", reclaimed[0].message_id)
    await redis_client.delete(stream_name)


async def test_bus__dead_letter_on_poison_event(
    redis_client: Redis, stream_name: str
) -> None:
    bus = RedisStreamsBus(redis_client)
    await bus.ensure_group(stream_name, "workers")
    await bus.publish(stream_name, {"event": "not-valid-json"})
    [message] = await bus.read_group(
        stream_name, "workers", "consumer-a", count=10, block_ms=100
    )

    await bus.dead_letter(
        stream_name, "workers", message, reason="schema validation failed"
    )

    assert await bus.dlq_depth(stream_name) == 1
    pending = await redis_client.xpending(stream_name, "workers")
    assert pending["pending"] == 0
    await redis_client.delete(stream_name, f"{stream_name}:dlq")


async def test_bus__lag_reports_undelivered_message_count(
    redis_client: Redis, stream_name: str
) -> None:
    bus = RedisStreamsBus(redis_client)
    await bus.ensure_group(stream_name, "workers")
    assert await bus.lag(stream_name, "workers") == 0

    await bus.publish(stream_name, {"event": "a"})
    await bus.publish(stream_name, {"event": "b"})
    assert await bus.lag(stream_name, "workers") == 2

    await bus.read_group(stream_name, "workers", "consumer-a", count=1, block_ms=100)
    assert await bus.lag(stream_name, "workers") == 1
    await redis_client.delete(stream_name)
