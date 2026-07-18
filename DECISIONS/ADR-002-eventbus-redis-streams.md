# ADR-002: EventBus interface with Redis Streams for MVP; Kafka deferred

- **Status:** accepted (supersedes proposal's Kafka choice)
- **Date:** 2026-07-18

## Context
The proposal specified Kafka. MVP throughput is a handful of demo agents —
tens of events/sec, spikes in the hundreds. Kafka (even KRaft single-node)
adds container weight, partition/consumer-group semantics, and operational
learning cost across every contributor, for durability/scale properties
nothing in the semester needs. Redis is already in the stack for SSE
fan-out. The subject-matter romance of "an event log for an event-log
product" is not an engineering argument.

## Decision
Define `EventBus` (publish, consumer-group subscribe, ack, DLQ) as a
Protocol in `trazo_server.bus`. Ship `RedisStreamsBus` (AOF enabled,
consumer groups, `XAUTOCLAIM` for crashed-consumer recovery) as the only
MVP implementation. Kafka becomes a post-MVP implementation of the same
interface, triggered by measured sustained ingest beyond a single stream's
comfort (ROADMAP #4).

## Consequences
Weeks of ops time redirected to replay. At-least-once semantics preserved
(consumers idempotent on `(run_id, seq)` regardless of bus). Cost: Redis
Streams lacks Kafka's retention/replay depth — acceptable because Postgres,
not the bus, is the system of record; the bus is transport. Revisit
trigger is quantitative, not aesthetic.
