"""Prometheus metrics (ARCHITECTURE.md §8, TRZ-P1-08, TRZ-P2-06).

Naming follows CODING_STANDARDS.md §3: ``trazo_<component>_<name>_<unit>``.
Scope here is the slice ARCHITECTURE §8 lists that already has a
component to measure — ingest rate, bus lag, DLQ depth, SSE client count.
Policy-eval latency and detector latency get their own metrics when those
components land (Phases 5/6).
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

SSE_CLIENTS = Gauge(
    "trazo_sse_clients",
    "Currently connected SSE clients.",
    ["endpoint"],  # runs | firehose
)
