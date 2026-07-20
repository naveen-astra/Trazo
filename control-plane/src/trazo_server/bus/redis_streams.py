"""Redis Streams implementation of EventBus (ADR-002).

MVP bus: one Redis Stream per logical stream (e.g. ``trazo:events``), one
consumer group per logical consumer (e.g. ``store-worker``); a poison
message is moved to ``<stream>:dlq``. Requires Redis 6.2+ for XAUTOCLAIM's
3-tuple return (next-cursor, claimed messages, deleted ids).

redis-py's stubs type stream responses as a broad Union covering both the
RESP2 (list-based) and RESP3 (dict-based) wire protocols, and type field
dicts against a Union of encodable types that's invariant against our
plain ``dict[str, str]``. We never opt into RESP3 (no ``protocol=3`` on the
client), so the shapes below are asserted, not guessed, and the `Any`
casts are structural (str is a member of every union involved) rather than
a real type hole.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from trazo_server.bus.protocol import BusMessage

_BUSYGROUP = "BUSYGROUP"


class RedisStreamsBus:
    """Implements trazo_server.bus.protocol.EventBus over redis.asyncio.Redis."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def publish(self, stream: str, fields: Mapping[str, str]) -> str:
        fields_dict: dict[str, str] = dict(fields)
        message_id = await self._redis.xadd(stream, cast(dict[Any, Any], fields_dict))
        return str(message_id)

    async def ensure_group(self, stream: str, group: str) -> None:
        try:
            await self._redis.xgroup_create(stream, group, id="$", mkstream=True)
        except ResponseError as exc:
            if _BUSYGROUP not in str(exc):
                raise

    async def read_group(
        self,
        stream: str,
        group: str,
        consumer: str,
        *,
        count: int,
        block_ms: int,
    ) -> list[BusMessage]:
        response = await self._redis.xreadgroup(
            group, consumer, streams={stream: ">"}, count=count, block=block_ms
        )
        if not response:
            return []
        # RESP2 shape (the default, since we don't request protocol=3):
        # list[(stream_name, list[(message_id, {field: value})])].
        assert isinstance(response, list), "expected RESP2 list response"
        entries = cast("list[tuple[str, list[tuple[str, dict[str, str]]]]]", response)
        _stream_name, messages = entries[0]
        return [
            BusMessage(message_id=str(message_id), fields=dict(fields))
            for message_id, fields in messages
        ]

    async def ack(self, stream: str, group: str, message_id: str) -> None:
        await self._redis.xack(stream, group, message_id)

    async def reclaim_stale(
        self,
        stream: str,
        group: str,
        consumer: str,
        *,
        min_idle_ms: int,
        count: int,
    ) -> list[BusMessage]:
        raw = await self._redis.xautoclaim(
            stream,
            group,
            consumer,
            min_idle_time=min_idle_ms,
            start_id="0-0",
            count=count,
        )
        _next_id, claimed, _deleted = cast(
            "tuple[str, list[tuple[str, dict[str, str]]], list[str]]", raw
        )
        return [
            BusMessage(message_id=str(message_id), fields=dict(fields))
            for message_id, fields in claimed
        ]

    async def dead_letter(
        self, stream: str, group: str, message: BusMessage, reason: str
    ) -> None:
        dlq_fields: dict[str, str] = {
            **message.fields,
            "_dlq_reason": reason,
            "_dlq_source_id": message.message_id,
        }
        await self._redis.xadd(f"{stream}:dlq", cast(dict[Any, Any], dlq_fields))
        await self.ack(stream, group, message.message_id)

    async def dlq_depth(self, stream: str) -> int:
        return int(await self._redis.xlen(f"{stream}:dlq"))

    async def lag(self, stream: str, group: str) -> int:
        # XINFO GROUPS reports `lag` directly on Redis 7+: entries in the
        # stream not yet delivered to any consumer in this group.
        groups = await self._redis.xinfo_groups(stream)
        for info in groups:
            if info.get("name") == group:
                return int(info.get("lag") or 0)
        return 0
