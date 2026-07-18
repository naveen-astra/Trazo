# Trazo — Roadmap

Phase statuses are flipped here by phase-close PRs (IMPLEMENTATION_PLAN §5).

## Semester (MVP) milestones

| Phase | Status | Weeks | Milestone deliverable |
|---|---|---|---|
| P0 Scaffold | not started | 0.5 | Repo boots; CI green; compose stack up |
| P1 Schema + Ingest + Store | not started | w1–2 | Event schema v1 frozen; hand-crafted trace end-to-end |
| P2 SDK + LangGraph + dashboard v1 | not started | w3–4 | Live LangGraph trace visible in timeline |
| P3 CrewAI + demo agents | not started | w5–6 | Two realistic demo agents tracing nightly |
| P4 Replay engine | not started | w5–8 | ≥99% state fidelity verified on demo corpus |
| P5 Failure injection + detection | not started | w8–10 | Labeled corpus + scored detectors |
| P6 Policy + memory + dashboard v2 | not started | w10–11 | Live inline deny; memory inspector; replay stepper UI |
| P7 Benchmark + release | not started | w12 | Reproducible benchmark; tagged v0.1.0; MVP demo |

Milestone acceptance = the phase's smoke script + the deliverables listed
in its TASKS file, per Definition of Done (MASTER_PLAN §7).

## Post-MVP roadmap (ordered, each unlocked by demand or scale, not vibes)

1. **AutoGen adapter** — third framework; validates adapter contract
   generality claimed in the papers.
2. **Replay forking** — mutate a recorded boundary result, continue live
   from that point (bundle format already supports it).
3. **TypeScript SDK** — after the Python adapter contract survives three
   frameworks unchanged.
4. **Kafka `EventBus` implementation** — when sustained ingest exceeds
   what a single Redis Stream comfortably handles (measured, not guessed);
   interface exists from P1.
5. **ClickHouse analytics store** — when dashboard aggregate queries slow
   past budget on Postgres; `TraceStore` seam exists.
6. **OTel exporter** — walk events → GenAI-semconv spans; makes Trazo data
   visible in existing Grafana/Jaeger installs.
7. **AuthN/Z** — per-project API keys → OIDC SSO → RBAC; `project_id`
   already on every row.
8. **Auto-pause escalation** — policy `escalate` suspends the run awaiting
   human approval (needs framework-side pause hooks per adapter).
9. **LLM drift classifier GA** — if the stretch lands and survives FPR
   scrutiny.
10. **Hosted tier** — managed storage, SSO, compliance features; the
    open-core line stays exactly where MASTER_PLAN draws it: SDK, store,
    replay stay free forever.

## Explicit non-goals (do not roadmap these without a MASTER_PLAN change)

Evaluation/quality-scoring platform (Phoenix's lane); prompt management;
agent *building* framework; fresh-run outcome prediction.
