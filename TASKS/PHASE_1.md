# Phase 1 — Schema, Ingest, Store (weeks 1–2)

Goal: event schema v1 frozen; a hand-crafted trace flows HTTP → bus →
Postgres and is readable back, idempotently.
Checkpoint: `phase1.sh` — seed `schema/examples/sample_run.ndjson` via
ingest API, assert row counts, re-seed (idempotency), read events + run
rollup back via query API, DLQ empty.

| ID | Task | Lane | Size | Risk | Deps | DoD |
|---|---|---|---|---|---|---|
| TRZ-P1-01 | Author `schema/trace-event.v1.schema.json` implementing EVENTS.md exactly (envelope + all kind payloads + blob refs); `schema/examples/` incl. `sample_run.ndjson` (the §6 minimal run, fleshed out) | A+B | L | high | P0 | Examples validate; every EVENTS.md field present; paired A+B review |
| TRZ-P1-02 | Codegen/validation glue: pydantic models in a shared pattern for both packages (`trazo.core.events`, `trazo_server.events`) + CI contract job asserting model↔schema equivalence | B | M | med | P1-01 | Contract job fails on deliberate drift (tested) |
| TRZ-P1-03 | `EventBus` Protocol + `RedisStreamsBus` (publish, group consume, ack, XAUTOCLAIM recovery, DLQ stream) + in-memory fake for tests | A | M | med | P0 | Unit tests incl. crashed-consumer reclaim; DLQ on poison event |
| TRZ-P1-04 | Alembic baseline migration: DATABASE.md tables/indexes; `TraceStore` repo (upsert events, run rollup update, queries) + `BlobStore` fs impl | A | L | med | P1-01 | Migration idempotent; upsert on (run_id,seq) proven by test |
| TRZ-P1-05 | Ingest API: `POST /v1/ingest/events` (validate, partial accept, publish), `POST /ingest/blobs`, bearer-key middleware, problem-details errors | A | M | low | P1-02,03 | API_SPEC behaviors covered by integration tests |
| TRZ-P1-06 | Store worker: bus consumer → TraceStore persist, blob offload >32KB, run rollups, stale-run TTL job | A | M | med | P1-03,04 | Kill-and-restart mid-stream loses nothing (test) |
| TRZ-P1-07 | Query API: `GET /runs`, `/runs/{id}`, `/runs/{id}/events` with pagination | A | M | low | P1-04 | Pagination cursor stable under concurrent inserts |
| TRZ-P1-08 | Prometheus metrics + structlog baseline across control plane (ingest rate, bus lag, DLQ depth) | A | S | low | P1-05,06 | Metrics visible; Grafana JSON committed |
| TRZ-P1-09 | Freeze schema v1: version note in `schema/README`, CHANGELOG entry, tag `schema-v1.0` | A+B | S | low | P1-01..07 | Post-freeze changes require version bump (CI check) |
