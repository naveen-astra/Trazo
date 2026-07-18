# Phase 2 — SDK core, LangGraph adapter, dashboard v1 (weeks 3–4)

Goal: a real LangGraph agent traced live into the dashboard.
Checkpoint: `phase2.sh` — run toy LangGraph agent (in `sdk/tests/agents/`),
assert full event sequence in store (run/step/llm/tool events, hashes,
fingerprints present), SSE delivers events during the run, timeline renders
(playwright smoke).

| ID | Task | Lane | Size | Risk | Deps | DoD |
|---|---|---|---|---|---|---|
| TRZ-P2-01 | `trazo.core.context`: run/step contextvars, ULID gen, seq counter, `trazo.init` | B | M | low | P1-09 | Thread + nested-context tests |
| TRZ-P2-02 | `trazo.core.fingerprint`: canonical JSON (sorted keys, NFC, float repr) + per-kind normalizers; golden-file + hypothesis property tests | B | M | high | P1-09 | Golden files reviewed by A+B (shared with replay + server) |
| TRZ-P2-03 | `trazo.core.recorder` + buffer + shipper thread + disk spool + redactor; `boundary()` API with RECORD mode | B | L | high | P2-01,02 | Kill -9 spool-drain test; overhead micro-benchmark harness exists |
| TRZ-P2-04 | LangGraph adapter: `instrument(graph)` — step events via node middleware w/ state snapshot+hash, llm/tool capture via scoped callbacks, memory hooks | B | L | high | P2-03 | Boundary-coverage audit test: every LLM/tool call in toy agent intercepted (proxy-counted) |
| TRZ-P2-05 | `@trace_tool` / `@trace_llm` decorators (custom-agent escape hatch) | B | S | low | P2-03 | Used in one test agent |
| TRZ-P2-06 | SSE fan-out: bus → `GET /v1/live/runs/{id}` + firehose, Last-Event-ID resume | A | M | med | P1-06 | Reconnect resume test; client-count metric |
| TRZ-P2-07 | Dashboard: Runs list (rollups, status, live badge) + Run detail timeline (kind-colored events, step grouping, payload drawer w/ blob fetch) | C | L | low | P1-07, P2-06 | Renders seeded + live runs; no client-side business logic |
| TRZ-P2-08 | `trazo tail` + `trazo doctor` CLI | B | S | low | P2-03,06 | Docs in SDK.md §5 verified |
| TRZ-P2-09 | Overhead benchmark in nightly: toy agent ±SDK, assert ≤10% | B | S | med | P2-04 | Nightly job red if budget blown |
