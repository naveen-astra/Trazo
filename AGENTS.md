# Instructions for AI Coding Agents

You are contributing to Trazo. This file is your entry point; it is
deliberately short. The authority chain is:

**MASTER_PLAN.md → the doc owning your area → your task in TASKS/ → this file.**

## Before writing any code (mandatory reading order)

1. [MASTER_PLAN.md](MASTER_PLAN.md) — scope, philosophy, definition of done.
2. The document that owns your area (map in MASTER_PLAN §1). Minimum:
   - Touching events/payloads → [EVENTS.md](EVENTS.md)
   - Touching the SDK → [SDK.md](SDK.md)
   - Touching replay → [REPLAY_ENGINE.md](REPLAY_ENGINE.md) + ADR-004
   - Touching the server → [ARCHITECTURE.md](ARCHITECTURE.md), [API_SPEC.md](API_SPEC.md), [DATABASE.md](DATABASE.md)
   - Touching detectors → [AI_DEBUGGER.md](AI_DEBUGGER.md)
3. Your task's row in [TASKS/](TASKS/) — its Deps must be closed.
4. [CODING_STANDARDS.md](CODING_STANDARDS.md) and [CONTRIBUTING.md](CONTRIBUTING.md).

## Hard rules (violations get reverted, not fixed up)

- One PR = one task ID (`TRZ-Px-nn`). No unplanned work; propose via issue.
- Stay in your lane's write scope (IMPLEMENTATION_PLAN §3). `schema/`
  changes require lanes A+B review and a version note.
- The SDK must never crash or block the host agent (ARCHITECTURE §7).
  The only exceptions it may raise into user code: `PolicyDenied`,
  `ReplayDivergence`.
- Every non-deterministic boundary goes through `Recorder.boundary` —
  in both record and replay mode. A bypassed boundary is a
  highest-severity bug (silently corrupts replay).
- One fingerprint implementation (`trazo.core.fingerprint`). Never
  reimplement normalization anywhere else.
- Replay substitutes recorded results; it never issues live calls and
  never regenerates model output (ADR-004).
- Handbook docs are contracts: if code and doc disagree, the doc wins —
  or you change the doc in the same PR with review.
- No new infrastructure. New capability = new implementation of an
  existing port (`EventBus`, `BlobStore`, `TraceStore`, `Detector`) or an
  approved ADR first.
- Do not: regenerate lockfiles/golden files unless the task says so;
  "improve" adjacent code opportunistically; add a `utils` module; leave
  `DEBT(` comments without a linked issue.

## PR description must include

Task ID + DoD checklist (checked), docs consulted, commands you ran and
their results. Unverifiable claims are review rejects.

## When blocked or in conflict

Task conflicts with a doc → flag in the PR, doc wins meanwhile. Need
another lane's files → stop, comment on the task issue, wait for ack.
Genuine ambiguity → open an issue; do not guess silently.
