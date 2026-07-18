# ADR-001: Single monorepo for SDK, control plane, dashboard, demos, benchmark

- **Status:** accepted
- **Date:** 2026-07-18

## Context
The event schema couples every component. Multi-repo would make every
schema change a coordinated multi-repo release with version skew as the
default state — deadly for a small team with AI agents contributing in
parallel.

## Decision
One repository. Separate packages with separate lockfiles (`sdk/`,
`control-plane/`, `dashboard/`), one canonical `schema/` at the root that
all packages validate against in CI. Lane-scoped write access
(IMPLEMENTATION_PLAN §3) substitutes for repo boundaries.

## Consequences
Atomic cross-cutting changes (schema + SDK + server in one PR); single CI;
trivially consistent versions. Cost: path-filtered CI needed to keep PRs
fast; discipline (lanes) replaces hard repo walls. Revisit if the SDK
needs an independent release cadence post-v1.
