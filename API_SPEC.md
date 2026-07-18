# Trazo — Control Plane API Specification

Base URL: `http://localhost:8420/v1` (default). All bodies JSON unless
noted. Auth: `Authorization: Bearer ${TRAZO_API_KEY}` required on ingest
and policy endpoints (ADR-009). Errors: RFC 9457 problem-details.
Versioning: path-versioned (`/v1`); breaking changes require `/v2`.

## Design philosophy

- The API is a thin, boring surface over the store and bus — no business
  logic lives in handlers.
- Batch-first ingest: the SDK ships arrays, never single events.
- Reads are paginated (`limit` ≤ 1000, `cursor` opaque), immutable content
  is cacheable (`ETag` on bundles/blobs).
- Everything the dashboard renders comes from these endpoints — no
  privileged side channel.

## Endpoints

### Ingest

`POST /ingest/events` — body `{"events": [Envelope, ...]}` (≤ 500/batch,
≤ 5MB). Validates against `schema/trace-event.v1.schema.json`; publishes to
bus; returns `202 {"accepted": n, "rejected": [{index, reason}]}`. Partial
acceptance is normal; the SDK re-ships rejects to the spool, not the API.

`POST /ingest/blobs` — raw body, `Content-Type` + `X-Trazo-Sha256` headers;
409 on mismatch; `201 {"sha256": ...}`. Idempotent by content.

### Query

`GET /runs?project=&status=&limit=&cursor=` → run summaries (rollups
included).
`GET /runs/{run_id}` → full run row.
`GET /runs/{run_id}/events?kind=&after_seq=&limit=&cursor=` → ordered
events.
`GET /runs/{run_id}/replay-bundle` → NDJSON stream (manifest line, then
events by seq). Immutable once run is terminal; `ETag: run_id+finished_at`.
`GET /blobs/{sha256}` → blob bytes; immutable, cache forever.
`GET /runs/{run_id}/detections` / `GET /runs/{run_id}/policy-decisions` →
projection reads.

### Policy

`POST /policy/evaluate` — body:

```jsonc
{
  "run_id": "run_...",
  "action": { "kind": "tool.call", "fingerprint": "sha256:...",
              "tool_name": "send_email", "args_summary": {...},
              "side_effect_class": "external",
              "projected_cost_usd": 0.4 },
  "run_context": { "cost_usd_so_far": 3.2, "active_detections": ["loop"] }
}
```

Response `200 {"decision": "allow|deny|escalate", "policy_id": ...,
"reasons": [...], "eval_ms": n}`. Latency budget 150 ms; the server calls
OPA (`POST opa:8181/v1/data/trazo/decision`) and records a
`policy.decision` event before responding. `escalate` is returned to the
SDK, which raises for human handling in MVP (auto-pause is roadmap).

### Live

`GET /live/runs/{run_id}` — SSE (`text/event-stream`); each message is one
envelope, `id:` = seq, so `Last-Event-ID` reconnects resume without loss.
`GET /live/firehose?project=` — all events for a project (dashboard run
list).

### Ops

`GET /healthz` (process up), `GET /readyz` (Postgres + Redis reachable),
`GET /metrics` (Prometheus).

## SDK-side contract notes

- The SDK treats any 5xx / timeout on ingest as "spool and retry with
  exponential backoff, cap 60s"; it never blocks the agent.
- Policy calls are the only synchronous dependency; timeout behavior is
  governed by `TRAZO_POLICY_FAIL` (ADR-006).
