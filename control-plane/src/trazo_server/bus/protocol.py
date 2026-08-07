"""The EventBus port: the seam between ingest and the store worker.

Transport-only — the bus knows nothing about trace-event shapes. Callers
own field encoding (typically a single ``event`` field holding the
serialized JSON envelope); see trazo_server.events for the wire model.
MVP implementation is Redis Streams (RedisStreamsBus, ADR-002); a heavier
bus is a new implementation of this Protocol, not a rewrite.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

# How long a consumer's read blocks server-side waiting for new messages,
# and how long the client waits for that command's reply. The second MUST
# stay strictly greater than the first: they time the same round trip from
# opposite ends, so an equal pair is a race the client usually loses.
#
# These live together because that invariant is the whole point. redis-py 8
# changed its default socket_timeout to 5s while the workers already blocked
# for 5s, which wedged the store worker completely — every idle poll raised
# TimeoutError, and a batch delivered at the boundary went into the group's
# pending list with the client never seeing the reply. Relying on a library
# default for one half of a paired setting is what made that possible.
BUS_BLOCK_MS = 5_000
BUS_SOCKET_TIMEOUT_SECONDS = 15.0


@dataclass(frozen=True)
class BusMessage:
    """One message read off a stream, carrying enough to ack or dead-letter it."""

    message_id: str
    fields: dict[str, str]


class EventBus(Protocol):
    """Append-only stream bus with consumer-group semantics.

    Every method is safe to call concurrently from multiple consumer
    processes sharing the same ``group`` — that's the point of consumer
    groups: each message is delivered to exactly one consumer until acked,
    and ``reclaim_stale`` recovers messages whose consumer died mid-flight.
    """

    async def publish(self, stream: str, fields: Mapping[str, str]) -> str:
        """Append one message to ``stream``; returns the assigned message id."""
        ...

    async def ensure_group(self, stream: str, group: str) -> None:
        """Create ``group`` at the tail of ``stream`` if it doesn't exist yet.

        Idempotent: calling this for an already-existing group is a no-op.
        """
        ...

    async def read_group(
        self,
        stream: str,
        group: str,
        consumer: str,
        *,
        count: int,
        block_ms: int,
    ) -> list[BusMessage]:
        """Read up to ``count`` new messages for ``consumer``, blocking up to
        ``block_ms`` milliseconds if none are immediately available."""
        ...

    async def ack(self, stream: str, group: str, message_id: str) -> None:
        """Acknowledge successful processing, clearing the pending entry."""
        ...

    async def reclaim_stale(
        self,
        stream: str,
        group: str,
        consumer: str,
        *,
        min_idle_ms: int,
        count: int,
    ) -> list[BusMessage]:
        """Claim up to ``count`` messages idle at least ``min_idle_ms`` for
        ``consumer`` — recovery path for a crashed sibling consumer."""
        ...

    async def dead_letter(
        self, stream: str, group: str, message: BusMessage, reason: str
    ) -> None:
        """Move a poison message to ``<stream>:dlq`` and ack it off ``stream``."""
        ...

    async def dlq_depth(self, stream: str) -> int:
        """Pending message count on ``<stream>:dlq`` (feeds the P1-08 metric)."""
        ...

    async def lag(self, stream: str, group: str) -> int:
        """Messages published to ``stream`` but not yet delivered to any
        consumer in ``group`` (feeds the P1-08 bus-lag metric)."""
        ...
