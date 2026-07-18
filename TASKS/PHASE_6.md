# Phase 6 — Policy engine, memory inspector, dashboard v2 (weeks 10–11)

Goal: inline governance is real (a tool call is blocked *before*
executing); memory reads inspectable per step; replay usable from the UI.
Checkpoint: `phase6.sh` — cost-cap policy denies a demo tool call
(PolicyDenied raised, decision event recorded, run status `blocked`);
observe-mode records without blocking; memory panel shows retrieval docs;
replay stepper walks a corpus run.

| ID | Task | Lane | Size | Risk | Deps | DoD |
|---|---|---|---|---|---|---|
| TRZ-P6-01 | OPA integration: sidecar wiring, `policies/` bundle layout, `trazo/decision` entrypoint convention, `opa test` in CI | A | M | med | P0-02 | Policy unit tests run in CI |
| TRZ-P6-02 | Starter policies: cost-cap (absolute + projected), tool blocklist, active-detection gate ("deny external tools while loop detection active") | D | M | low | P6-01, P5-06 | Each policy has opa tests + docs in `policies/README` |
| TRZ-P6-03 | `POST /v1/policy/evaluate`: OPA delegate, decision event emit-before-respond, 150ms budget, eval-latency histogram | A | M | med | P6-01 | Latency budget asserted in integration test |
| TRZ-P6-04 | SDK PolicyHook: sync check on governed boundaries, off/observe/enforce, fail-open/closed, per-run decision cache, `PolicyDenied` | B | L | high | P6-03, P2-04 | Blocked call provably never executes (side-effect sentinel test); cache hit path measured |
| TRZ-P6-05 | Policy surfacing: projections endpoint + dashboard decisions panel (per-run, with reasons) | A+C | S | low | P6-03 | Deny visible in UI with policy id + reasons |
| TRZ-P6-06 | Memory inspector: dashboard per-step panel rendering `memory.read` results (docs, scores, query) with blob fetch | C | M | low | P2-07 | Research-assistant retrievals fully inspectable |
| TRZ-P6-07 | Replay stepper UI: bundle-driven step list, state before/after diff view, boundary event inline, divergence display (lenient report) | C | L | med | P4-05 | Steps through corpus run; renders a divergence report fixture |
