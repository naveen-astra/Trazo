# Trazo — Engineering Master Plan

> **This is the root document of the Trazo engineering handbook.** Every other
> document in this repository hangs off this one. If you are an engineer or an
> AI coding agent about to write code: read this file first, then the documents
> it points you to for your task. If a decision you're about to make
> contradicts something written here, stop and open an issue — do not silently
> diverge.

---

## 1. Document map

| Document | What it owns |
|---|---|
| [MASTER_PLAN.md](MASTER_PLAN.md) | Vision, scope, MVP boundary, engineering philosophy, definition of done |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System architecture, components, data/runtime flow, security, config, errors, logging |
| [EVENTS.md](EVENTS.md) | The canonical trace event model — the single most load-bearing contract |
| [DATABASE.md](DATABASE.md) | Schema, entity relationships, retention |
| [API_SPEC.md](API_SPEC.md) | Control-plane HTTP API and live-stream contract |
| [SDK.md](SDK.md) | SDK architecture, adapter contract, record/replay interception |
| [REPLAY_ENGINE.md](REPLAY_ENGINE.md) | Replay semantics, fingerprinting, divergence handling |
| [AI_DEBUGGER.md](AI_DEBUGGER.md) | Anomaly detection: failure taxonomy, rule detectors, LLM classifier |
| [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) | Build order, task decomposition, parallelization, integration checkpoints |
| [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) | Environment setup, workflow, testing strategy, CI |
| [CODING_STANDARDS.md](CODING_STANDARDS.md) | Conventions, naming, patterns, review bar |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Process for humans and AI agents: claiming tasks, PRs, merge strategy |
| [ROADMAP.md](ROADMAP.md) | Milestones, timeline, deliverables, post-MVP direction |
| [RESEARCH.md](RESEARCH.md) | Research questions, experiment designs, benchmark plan |
| [DECISIONS/](DECISIONS/) | Architecture Decision Records — why things are the way they are |
| [TASKS/](TASKS/) | Per-phase task breakdowns with IDs, dependencies, and DoD |
| [AGENTS.md](AGENTS.md) | Entry-point rules for AI coding agents (authority chain, hard rules) |
| [GLOSSARY.md](GLOSSARY.md) | Canonical vocabulary — terms used identically in docs, code, and UI |

---

## 2. Vision

**Trazo is the observability, replay, and governance layer for multi-agent AI
systems** — the layer that sits between agent frameworks (LangGraph, CrewAI,
AutoGen) and the engineers who must keep agents built on them running
correctly. The analogy that anchors every design decision: Datadog's
relationship to application code, and Temporal's relationship to workflow
code, purpose-built for how agent systems actually fail.

Three capabilities define the product, in strict priority order:

1. **Trace** — capture every state transition, LLM call, tool call, memory
   access, and inter-agent message of an instrumented run as durable,
   individually addressable events, uniformly across frameworks.
2. **Replay** — deterministically re-drive a historical run step by step,
   substituting recorded LLM/tool/memory results at every non-deterministic
   boundary. This is the core technical bet and the project's reason to exist.
3. **Govern** — detect degenerate execution patterns (loops, budget runaways,
   drift) and enforce policies *before* an action executes, not after.

The order matters: replay depends on trace quality; governance depends on
both. A beautiful dashboard with fake replay is a failed project. A working
replay engine with an ugly dashboard is a successful one.

## 3. Engineering philosophy

These are the operating principles. ADRs cite them; reviews enforce them.

1. **The event schema is the product.** Every component — store, replay,
   detection, policy, dashboard — is a consumer of one canonical event model
   ([EVENTS.md](EVENTS.md)). Schema changes are the most expensive changes in
   the system and get the most scrutiny.
2. **Interfaces over infrastructure.** Every piece of infrastructure hides
   behind a small internal interface (`EventBus`, `BlobStore`, `TraceStore`).
   MVP implementations are the simplest thing that works (Redis Streams,
   filesystem, Postgres); heavier options (Kafka, MinIO, ClickHouse) are
   swap-ins, not rewrites. See ADR-002, ADR-003, ADR-010.
3. **Record, don't regenerate.** Replay substitutes recorded values at
   non-deterministic boundaries. We never claim to reproduce fresh LLM
   sampling. See ADR-004 and [REPLAY_ENGINE.md](REPLAY_ENGINE.md).
4. **Stand on OpenTelemetry's shoulders.** The event schema stays convertible
   to OTel GenAI semantic conventions. We extend; we do not fork the
   ecosystem. See ADR-005.
5. **The hard 20% first.** Roadmap order is dependency order, and replay is
   scheduled early and long (three weeks), because the biggest failure mode of
   this project is polishing the easy 80% and faking the hard part.
6. **Every non-trivial decision gets an ADR.** If a future agent asks "why is
   it like this," the answer must be a document, not archaeology.
7. **Boring technology, deliberately.** Postgres, Redis, FastAPI, React. The
   novelty budget is spent entirely on replay semantics and the failure
   taxonomy — never on infrastructure.
8. **Observable by construction.** Trazo watches agents; it must be watchable
   itself: structured logs, Prometheus metrics, health endpoints from day one.

## 4. Product scope

### 4.1 In scope (MVP — one semester)

| Capability | Scope commitment |
|---|---|
| Trace event schema | v1 frozen at end of Phase 1; OTel-GenAI-aligned; versioned envelope |
| Python SDK | Core recorder + context propagation + buffering/batch ship |
| LangGraph adapter | Full: state transitions, LLM calls, tool calls, memory hooks |
| CrewAI adapter | Full: task/agent lifecycle, tool calls, delegation messages |
| Ingestion | HTTP batch ingest → Redis Streams → store worker → Postgres |
| Trace store | Postgres (events, runs, artifacts index); filesystem/MinIO blob offload |
| Replay engine | Record/substitute replay of a historical run; step API; divergence detection; fidelity verification harness |
| Anomaly detection | Rule-based detectors: loop, budget runaway, tool thrash; detection events written back into the pipeline |
| Policy engine | OPA sidecar; synchronous SDK pre-action hook; cost-cap + tool-blocklist policies; audit decisions recorded |
| Dashboard | Run list, trace timeline, step inspector (incl. memory reads), replay stepper, detection badges; live tail via SSE |
| Demo agents | Research assistant (LangGraph), content pipeline (CrewAI) + failure-injection harness |
| Benchmark | Replay-fidelity rate + detector precision/recall/FPR on injected failures |

### 4.2 Deliberately excluded from MVP

Each exclusion is a decision, not an accident. Reversal requires an ADR.

| Excluded | Why | Where it lives |
|---|---|---|
| Kafka | Operational weight with zero payoff at MVP throughput; `EventBus` interface keeps the door open | ADR-002, ROADMAP |
| ClickHouse / TimescaleDB | Postgres handles demo-scale trivially; analytics store is a scale problem we don't have yet | ADR-003, ROADMAP |
| Kubernetes (Minikube/Kind) | Docker Compose reproduces the full stack in one command; K8s adds setup cost, no design pressure | ADR-007, ROADMAP |
| AutoGen adapter | Two frameworks prove cross-framework claims; the third is additive, not architectural | ROADMAP |
| TypeScript SDK | Python is where the agent frameworks are; TS doubles surface area | ADR-008, ROADMAP |
| Auth / RBAC / SSO | Single-team self-hosted MVP; static API key on ingest is enough | ADR-009, ROADMAP |
| LLM-based drift detection | Rules cover 3 of 4 failure classes measurably; the LLM classifier is a stretch goal inside Phase 5, cuttable without harming the benchmark | AI_DEBUGGER.md |
| Replay forking ("what if") | Requires replay v1 to exist and be trusted first | REPLAY_ENGINE.md, ROADMAP |
| Hosted/SaaS anything | Open-core hosting is a business-model question, not a semester deliverable | ROADMAP |

### 4.3 MVP definition (the demo that must work)

At the end of the semester, this scripted demo must run live, unfaked:

1. `docker compose up` brings up the full stack.
2. Run the LangGraph demo agent with the SDK enabled; watch its trace stream
   into the dashboard live.
3. Inject a tool-call loop via the failure harness; watch the loop detector
   flag the run *while it executes*.
4. Set a cost-cap policy; re-run; watch the SDK block the over-budget tool
   call *before it executes*, with the denial recorded in the trace.
5. Open yesterday's failed run. Step through it in the replay view. Show that
   at step N the replayed state hash matches the recorded state hash.
6. Run the fidelity harness across all recorded demo runs; show the
   replay-fidelity number.

Anything in the codebase that doesn't serve that demo or the benchmark is
scope creep.

## 5. What changed from the original proposal, and why

The proposal ([final-project-decision](final-project-decision-agenttrace-%20Trazo.md))
is directionally right and its risk analysis ("teams polish the dashboard and
fake replay") is correct — so this plan restructures the infrastructure to
spend the saved weeks on replay:

| Proposal said | Plan says | Rationale |
|---|---|---|
| Kafka event bus | `EventBus` interface; Redis Streams MVP | Kafka ops cost ≈ 1–2 weeks across the semester; zero benefit below thousands of events/sec (ADR-002) |
| Postgres + ClickHouse | Postgres only | No analytical workload exists yet (ADR-003) |
| Minikube/Kind | Docker Compose | Reproducibility without cluster ops (ADR-007) |
| 3 adapters (LangGraph/CrewAI/AutoGen) | 2 adapters | Proposal's own MVP section (§11) already said this; formalized |
| Supabase auth, RBAC week 10 | API-key stub only | Auth serves the hosted tier, which doesn't exist yet (ADR-009) |
| Replay week 5 (one week) | Replay Phase 4 (three weeks) | The proposal's own "brutal reality check" demands this |
| Anomaly = rules + LLM | Rules required; LLM stretch | Benchmark integrity needs measurable detectors, not demos |

## 6. Quality standard

- Every merged PR maps to a task ID in [TASKS/](TASKS/).
- Every public function/class in the SDK has a docstring; every module has a
  module docstring stating its single responsibility.
- Test coverage: SDK core and replay engine ≥ 85% line coverage; control
  plane ≥ 75%; adapters exercised by integration tests against real
  framework versions pinned in lockfiles.
- No PR merges with failing CI. No `# type: ignore` without a linked issue.
- Performance budget: SDK instrumentation overhead ≤ 10% wall-clock on demo
  agents; ingest path handles 1,000 events/sec on a laptop.

## 7. Definition of Done

**A task is done when:** code + tests merged; docs updated in the same PR;
CI green; the task's DoD checklist in its TASKS file is satisfied; no new
lint/type errors.

**A phase is done when:** its integration checkpoint
([IMPLEMENTATION_PLAN.md §6](IMPLEMENTATION_PLAN.md)) passes end-to-end on a
clean `docker compose up`, demonstrated by the phase's smoke script in
`scripts/smoke/`.

**The MVP is done when:** the §4.3 demo runs unfaked, the benchmark numbers
in [RESEARCH.md](RESEARCH.md) are produced by CI-runnable scripts, and a
tagged release installs via `pip install trazo` from a local wheel.

## 8. Success metrics

| Metric | Target |
|---|---|
| Replay fidelity (state-match rate across benchmark runs) | ≥ 99% strict-mode step matches on unchanged code |
| Replay overhead vs. live run | ≤ 25% wall-clock |
| Loop/budget/thrash detector | Precision ≥ 0.9, Recall ≥ 0.85 on injected failures |
| Detector false-positive rate on clean runs | ≤ 5% |
| SDK overhead | ≤ 10% wall-clock |
| Time-to-first-trace for a new user | ≤ 15 minutes from clone |
