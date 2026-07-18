# ADR-008: Python-first SDK; TypeScript deferred

- **Status:** accepted
- **Date:** 2026-07-18

## Context
LangGraph, CrewAI, and AutoGen are Python-native; that's where the target
user's agents run. A TS SDK doubles the surface (recorder, fingerprint,
spool, replay driver) before the adapter contract has survived contact
with even one framework.

## Decision
Python ≥ 3.10 SDK only for MVP. The adapter contract (SDK.md §3) and the
wire schema are the portability layer: a future TS SDK implements the same
contract against the same schema, gated on the contract surviving three
Python frameworks unchanged (ROADMAP #3).

## Consequences
Full engineering focus on one runtime's edge cases (threading, atexit,
contextvars). Cost: JS-based agent stacks (e.g. LangGraph.js) are out of
reach for now — accepted; the wire protocol keeps them reachable later.
