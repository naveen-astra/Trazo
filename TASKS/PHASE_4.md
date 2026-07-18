# Phase 4 — Replay engine (weeks 5–8, parallel lane; the core bet)

Goal: REPLAY_ENGINE.md implemented for real. This phase gets the most
senior attention and the least tolerance for shortcuts.
Checkpoint: `phase4.sh` — `trazo verify` over ≥ 20 corpus runs reports
state fidelity ≥ 0.99; a deliberately mutated agent produces a
`ReplayDivergence` whose reported first-divergence matches the mutation
point; replay overhead ≤ 0.25.

| ID | Task | Lane | Size | Risk | Deps | DoD |
|---|---|---|---|---|---|---|
| TRZ-P4-01 | Replay bundle: `GET /runs/{id}/replay-bundle` NDJSON (manifest+events), `GET /blobs/{sha}`, ETag/immutability; SDK-side bundle loader + `.trazo/cache/` | A+B | M | low | P1-07 | Bundle round-trips sample corpus byte-stable |
| TRZ-P4-02 | Substituter: per-kind cursors, exact + K=3 lookahead matching, recorded-result return path through `Recorder.boundary` REPLAY mode | B | L | high | P2-03, P4-01 | Record→replay of scripted toy run: zero divergence, zero live calls (network guard asserts) |
| TRZ-P4-03 | Divergence machinery: strict/lenient modes, `ReplayDivergence` with field-level normalized-input diff, replay report model | B | M | high | P4-02 | Mutation localization test (prompt edit, tool-arg edit, reorder) |
| TRZ-P4-04 | Determinism aids: seeded `random`/numpy, frozen time within replay context; per-adapter documentation of residual gaps | B | M | med | P4-02 | Aids measurably reduce divergence on demo corpus (before/after numbers in PR) |
| TRZ-P4-05 | Step API + entrypoint registration: `session.steps()`, `step.verify()` (state_before → re-drive → compare state_after_hash), `run_to(n)` | B | L | high | P4-02,03 | REPLAY_ENGINE §4 examples run as doctests |
| TRZ-P4-06 | `trazo replay` + `trazo verify` CLI (fidelity report: boundary, state, overhead) | B | M | low | P4-05 | Human-readable + `--json` outputs |
| TRZ-P4-07 | Fidelity harness `benchmark/fidelity/`: run verify across corpus index, emit RESEARCH.md RQ1 table | D | M | med | P4-06, P3-05 | One command regenerates the table |
| TRZ-P4-08 | LangGraph + CrewAI replay integration tests in CI (cassette-backed, both frameworks) | B | M | high | P4-05, P3-01 | Green in CI without live LLM calls |
