# ADR-009: Static API key auth for MVP; no Supabase/RBAC/SSO

- **Status:** accepted
- **Date:** 2026-07-18

## Context
Proposal budgeted Supabase auth and week-10 RBAC. The MVP deployment
reality is a single team self-hosting on localhost/dev boxes. Auth
infrastructure serves the hosted tier — which is explicitly not a
semester deliverable — and costs integration time now.

## Decision
One static bearer key (`TRAZO_API_KEY`) guards ingest and policy
endpoints; query/dashboard bind to localhost by default. Tenancy
readiness is preserved structurally: `project_id` on every table and
every query path, so per-project keys → OIDC → RBAC layer on without
schema migration (ROADMAP #7).

## Consequences
Days saved; honest security posture documented (ARCHITECTURE §5) instead
of security theater. Cost: not multi-tenant-safe — stated loudly in
README at release. Revisit at first external-user deployment.
