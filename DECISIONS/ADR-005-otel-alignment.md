# ADR-005: Event schema is a superset aligned with OTel GenAI semconv

- **Status:** accepted
- **Date:** 2026-07-18

## Context
OpenTelemetry's GenAI semantic conventions standardize LLM-call span
attributes. Inventing a competing vocabulary would orphan Trazo data from
the existing observability ecosystem; adopting OTel wholesale would
straitjacket replay (OTel has no fingerprints, state hashes, policy
decisions, or detections).

## Decision
Trazo's envelope is its own (replay needs `seq`, fingerprints, state
hashes), but every field with a GenAI-semconv equivalent uses semconv
vocabulary and semantics (`gen_ai.request.model`, `gen_ai.usage.*` naming
in `llm.call` payloads). An events→OTel-spans exporter is a planned
post-MVP bridge (ROADMAP #6). Rule: no Trazo field may duplicate a
semconv concept under a different name.

## Consequences
Existing OTel tooling remains reachable; schema reviews carry a semconv
check. Cost: occasional awkward names inherited from semconv; tracked
against semconv's own evolution (it is still stabilizing — pin the
referenced revision in `schema/README`).
