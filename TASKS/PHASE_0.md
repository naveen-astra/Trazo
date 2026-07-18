# Phase 0 — Scaffold (0.5 week)

Goal: an empty-but-real monorepo where every later task has a slot, CI is
green, and `make up` boots the stack.
Checkpoint: `scripts/smoke/phase0.sh` — compose up, `/healthz` and
`/readyz` return 200, dashboard placeholder serves, `make test` passes.

| ID | Task | Lane | Size | Risk | Deps | DoD |
|---|---|---|---|---|---|---|
| TRZ-P0-01 | Repo layout per ARCHITECTURE §2.4: `sdk/`, `control-plane/`, `dashboard/`, `schema/`, `policies/`, `demos/`, `benchmark/`, `deploy/`, `scripts/smoke/`; root `Makefile`, `pyproject.toml` (ruff/mypy config), `.pre-commit-config.yaml` | A | M | low | — | Tree matches doc; `make lint` runs clean on stubs |
| TRZ-P0-02 | `deploy/docker-compose.yml`: postgres16, redis7 (AOF), opa, control-plane (stub FastAPI with `/healthz` `/readyz` `/metrics`), dashboard (vite placeholder); `.env.example`; `make up/down/nuke` | A | M | low | P0-01 | Clean-machine `make up` reaches healthy state |
| TRZ-P0-03 | Python packaging: `sdk` + `trazo_server` installable via uv, split lockfiles, pytest wired, one placeholder test each | B | S | low | P0-01 | `make test` green |
| TRZ-P0-04 | Dashboard scaffold: Vite + React + TS strict + ESLint/Prettier + TanStack Query + router; placeholder Runs page | C | S | low | P0-01 | `make dev-dash` serves; `make lint` covers TS |
| TRZ-P0-05 | CI: `ci.yml` (path-filtered lint/type/unit/contract/integration jobs), `nightly.yml` skeleton, commitlint on PR titles | A | M | low | P0-02,03,04 | CI green on a no-op PR; path filtering verified |
| TRZ-P0-06 | `scripts/smoke/phase0.sh` + smoke-runner convention (`make smoke PHASE=n`) | A | S | low | P0-02 | Script exits 0 against fresh compose |
