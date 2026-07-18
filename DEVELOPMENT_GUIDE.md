# Trazo — Development Guide

## 1. Prerequisites

Docker + Docker Compose v2, Python 3.11 (managed via `uv`), Node 20 + npm,
`make`. Optional: Ollama (only for the drift-classifier stretch).

## 2. First run

```bash
git clone <repo> && cd trazo
cp deploy/.env.example deploy/.env
make up          # docker compose up: postgres, redis, opa, control-plane, dashboard
make seed        # ingest the hand-crafted sample trace (schema/examples/)
open http://localhost:5173   # dashboard shows the seeded run
```

`make down` stops everything; `make nuke` also deletes volumes.

## 3. Day-to-day workflow

```bash
make dev-server   # control-plane with reload, against compose postgres/redis
make dev-dash     # vite dev server
make test         # all python tests (sdk + control-plane), unit only
make test-int     # integration tests (needs compose up)
make lint         # ruff + mypy + eslint + prettier-check
make smoke PHASE=2
make demo AGENT=research-assistant   # run a demo agent instrumented
```

Python env: `uv sync` inside `sdk/` and `control-plane/` (separate venvs,
separate lockfiles — the SDK must never accidentally depend on server
libs). Pre-commit hooks (`pre-commit install`) run ruff/format/mypy on
changed files.

## 4. Testing strategy (project-wide)

| Layer | Tooling | Gate |
|---|---|---|
| Unit (SDK core, detectors, fingerprint, store repos) | pytest, hypothesis for fingerprint/canonicalization | every PR; coverage gates per MASTER_PLAN §6 |
| Contract | SDK + server event models validated against `schema/*.json` golden files | every PR |
| Integration | pytest against live compose (ingest→store→query; record→replay) | every PR (compose in CI service containers) |
| E2E smoke | `scripts/smoke/phase<N>.sh` | merge to main + nightly |
| Overhead benchmark | instrumented vs. bare demo agent, asserts ≤ 10% | nightly |
| Adapter matrix | LangGraph/CrewAI pinned min + latest versions | nightly |

Test naming: `test_<unit>__<behavior>` (double underscore separates
subject from expectation). Fixtures for event streams live in
`schema/examples/` and are shared by SDK, server, and benchmark tests —
one corpus, three consumers.

## 5. CI (GitHub Actions)

Workflows: `ci.yml` (lint → unit → contract → integration, path-filtered
per lane so dashboard-only PRs skip python jobs), `nightly.yml` (smoke,
adapter matrix, overhead benchmark, demo-agent trace generation),
`release.yml` (tag → build wheels + dashboard bundle + compose archive →
GitHub Release). CI must stay under the free-tier budget: integration jobs
use a single compose project, no matrix beyond the adapter job.

## 6. Git workflow

Trunk-based (IMPLEMENTATION_PLAN §6). Branch: `lane/TRZ-P2-03-recorder`.
Conventional commits (`feat:`, `fix:`, `docs:`, `test:`, `chore:`) —
enforced by commitlint in CI on PR titles (squash merge uses the PR
title). One task ID per PR; if a PR needs two IDs it's two PRs.
