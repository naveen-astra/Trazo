# ADR-004: Replay = record-and-substitute; never regenerate

- **Status:** accepted
- **Date:** 2026-07-18

## Context
LLM completions are sampled; providers rotate weights; external tools are
time-varying. "Run it again" produces a second uncorrelated run, not a
replay. Temporal solved the isomorphic problem for workflows by replaying
control flow against recorded Activity results.

## Decision
Every non-deterministic boundary (`llm.call`, `tool.call`, `memory.read`,
`human.checkpoint`) is recorded verbatim with an input fingerprint. Replay
re-drives real agent code and substitutes recorded results by
fingerprint+cursor match (REPLAY_ENGINE §2). Divergence is a first-class,
diffed, reported outcome — never silently papered over. Fresh-run
prediction is explicitly out of scope.

## Consequences
Replay is faithful, fast (no live calls), and honest about its limits.
Cost: adapters must intercept *every* boundary (a missed one silently
corrupts replay — treated as highest-severity bug class); storage carries
full boundary I/O (mitigated by blob offload + dedupe). This ADR is the
project's core identity; superseding it means the project changed.
