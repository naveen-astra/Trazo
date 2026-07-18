# ADR-003: Postgres as the only trace store in MVP; ClickHouse deferred

- **Status:** accepted
- **Date:** 2026-07-18

## Context
Proposal listed Postgres + optional ClickHouse/TimescaleDB. The MVP's
query load is: fetch a run's events in order (replay bundle), filtered
kind queries, run-list rollups. All are index-friendly OLTP reads at
demo-corpus scale (≤ a few million rows). There is no analytical workload
yet to justify a second store, second schema, and dual-write complexity.

## Decision
Postgres 16 only, behind a `TraceStore` repository interface. JSONB
payloads with targeted GIN index; rollups maintained by the store worker
rather than computed by wide scans. ClickHouse becomes a `TraceStore`-
adjacent analytics read path only when a measured dashboard query exceeds
budget (ROADMAP #5).

## Consequences
One database to migrate, back up, and reason about; the repository seam
makes the analytics store additive later. Cost: very large aggregate
queries would be slow today — none exist in the MVP feature list, and the
feature list is the scope contract.
