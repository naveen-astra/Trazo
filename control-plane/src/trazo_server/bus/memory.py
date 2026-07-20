"""In-memory EventBus fake: same Protocol as RedisStreamsBus, no Redis needed.

Used by unit tests (this package's and the store worker's) that need real
consumer-group semantics — pending entries, crashed-consumer reclaim, DLQ —
without the cost or flakiness of a live Redis. Not for production use.
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from trazo_server.bus.protocol import BusMessage


@dataclass
class _GroupState:
    """Per-(stream, group) delivery cursor and pending-entries list (PEL)."""

    next_offset: int = 0
    # message_id -> (owning consumer, last-delivered-at)
    pending: dict[str, tuple[str, float]] = field(default_factory=dict)


class InMemoryEventBus:
    """Implements trazo_server.bus.protocol.EventBus over plain Python state."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._streams: dict[str, list[tuple[str, dict[str, str]]]] = defaultdict(list)
        self._groups: dict[tuple[str, str], _GroupState] = {}
        self._seq = 0

    def _next_id(self) -> str:
        self._seq += 1
        return f"{self._seq}-0"

    def _find(self, stream: str, message_id: str) -> dict[str, str] | None:
        for mid, fields in self._streams[stream]:
            if mid == message_id:
                return fields
        return None

    async def publish(self, stream: str, fields: Mapping[str, str]) -> str:
        message_id = self._next_id()
        self._streams[stream].append((message_id, dict(fields)))
        return message_id

    async def ensure_group(self, stream: str, group: str) -> None:
        self._groups.setdefault((stream, group), _GroupState())

    async def read_group(
        self,
        stream: str,
        group: str,
        consumer: str,
        *,
        count: int,
        block_ms: int,
    ) -> list[BusMessage]:
        del block_ms  # the fake never blocks; it just returns what's available
        state = self._groups[(stream, group)]
        entries = self._streams[stream][state.next_offset : state.next_offset + count]
        now = self._clock()
        out = []
        for message_id, fields in entries:
            state.pending[message_id] = (consumer, now)
            out.append(BusMessage(message_id=message_id, fields=dict(fields)))
        state.next_offset += len(entries)
        return out

    async def ack(self, stream: str, group: str, message_id: str) -> None:
        self._groups[(stream, group)].pending.pop(message_id, None)

    async def reclaim_stale(
        self,
        stream: str,
        group: str,
        consumer: str,
        *,
        min_idle_ms: int,
        count: int,
    ) -> list[BusMessage]:
        state = self._groups[(stream, group)]
        now = self._clock()
        claimed: list[BusMessage] = []
        for message_id, (_owner, delivered_at) in list(state.pending.items()):
            if len(claimed) >= count:
                break
            idle_ms = (now - delivered_at) * 1000
            if idle_ms < min_idle_ms:
                continue
            fields = self._find(stream, message_id)
            if fields is None:
                state.pending.pop(message_id, None)
                continue
            state.pending[message_id] = (consumer, now)
            claimed.append(BusMessage(message_id=message_id, fields=dict(fields)))
        return claimed

    async def dead_letter(
        self, stream: str, group: str, message: BusMessage, reason: str
    ) -> None:
        dlq_fields = {
            **message.fields,
            "_dlq_reason": reason,
            "_dlq_source_id": message.message_id,
        }
        dlq_stream = f"{stream}:dlq"
        self._streams[dlq_stream].append((self._next_id(), dlq_fields))
        await self.ack(stream, group, message.message_id)

    async def dlq_depth(self, stream: str) -> int:
        return len(self._streams[f"{stream}:dlq"])

    async def lag(self, stream: str, group: str) -> int:
        state = self._groups.get((stream, group))
        if state is None:
            return len(self._streams[stream])
        return len(self._streams[stream]) - state.next_offset
