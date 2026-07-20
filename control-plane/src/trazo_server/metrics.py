"""Prometheus metrics (ARCHITECTURE.md §8, TRZ-P1-08).

Naming follows CODING_STANDARDS.md §3: ``trazo_<component>_<name>_<unit>``.
Scope here is exactly the phase-1 slice ARCHITECTURE §8 lists that already
has a component to measure — ingest rate, bus lag, DLQ depth. Policy-eval
latency, detector latency, and SSE client count get their own metrics when
those components land (Phases 5/6).
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge

INGEST_EVENTS_TOTAL = Counter(
    "trazo_ingest_events_total",
    "Ingest API events processed, by outcome.",
    ["result"],  # accepted | rejected
)

INGEST_BLOBS_TOTAL = Counter(
    "trazo_ingest_blobs_total",
    "Ingest API blob uploads processed, by outcome.",
    ["result"],  # stored | checksum_mismatch
)

BUS_LAG_MESSAGES = Gauge(
    "trazo_bus_lag_messages",
    "Messages published but not yet delivered to the store-worker consumer group.",
)

BUS_DLQ_DEPTH_MESSAGES = Gauge(
    "trazo_bus_dlq_depth_messages",
    "Pending messages on the events dead-letter stream.",
)
