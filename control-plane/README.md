# trazo-server (control plane)

The FastAPI service owning ingest, query, policy, and live-stream APIs, plus
the in-process store and detector workers (separable later).

Status: Phase 1 in progress. Landed so far: event models (`events.py`);
the `EventBus` port + `RedisStreamsBus`/`InMemoryEventBus` (TRZ-P1-03); the
`TraceStore`/`BlobStore` ports + Postgres/filesystem impls + Alembic
baseline migration (TRZ-P1-04); the ingest API (`POST /v1/ingest/events`,
`POST /v1/ingest/blobs`, bearer auth, RFC 9457 errors — TRZ-P1-05); the
in-process store worker (consume → persist → blob-offload → run rollup →
stale-run sweep, `TRAZO_FEATURE_STORE_WORKER` flag — TRZ-P1-06); the query
API (`GET /v1/runs`, `/v1/runs/{id}`, `/v1/runs/{id}/events`, keyset
pagination, unauthenticated per ADR-009 — TRZ-P1-07); real `/readyz`
(Postgres + Redis reachability), Prometheus metrics (ingest rate, bus lag,
DLQ depth), structlog JSON baseline with request-id context, and the
Grafana dashboard under `deploy/grafana/` (TRZ-P1-08). Not yet landed: the
schema-v1 freeze and the phase-1 smoke script. The API contract is
[API_SPEC.md](../API_SPEC.md); storage is [DATABASE.md](../DATABASE.md);
module boundaries are ARCHITECTURE section 2.2. See
[TASKS/PHASE_1.md](../TASKS/PHASE_1.md) for the remaining tasks.

Development:

```bash
cd control-plane
uv sync
uv run pytest
uv run python -m trazo_server   # serves on :8420
```
