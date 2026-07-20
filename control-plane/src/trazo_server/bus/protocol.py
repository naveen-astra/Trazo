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
