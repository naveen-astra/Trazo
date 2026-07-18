# Phase 3 — CrewAI adapter + demo agents (weeks 5–6a, Lane B/D while Lane B' starts P4)

Goal: cross-framework claim becomes real; realistic trace corpus starts
accumulating nightly.
Checkpoint: `phase3.sh` — both demo agents run instrumented end-to-end;
traces meet a realism bar (≥ 15 steps, ≥ 2 agents/roles, ≥ 5 tool calls,
memory events present); nightly corpus job green.

| ID | Task | Lane | Size | Risk | Deps | DoD |
|---|---|---|---|---|---|---|
| TRZ-P3-01 | CrewAI adapter: task lifecycle → steps, delegation → `agent.message`, tool registry wrapping, memory capture | B | L | high | P2-04 | Boundary-coverage audit vs. toy crew; version range pinned |
| TRZ-P3-02 | Demo agent 1 — research assistant (LangGraph): plan→search→retrieve→synthesize w/ vector memory (chroma local), 3+ tools | D | M | low | P2-04 | Deterministic-ish fixture inputs; trace realism bar met |
| TRZ-P3-03 | Demo agent 2 — content pipeline (CrewAI): researcher/writer/editor crew, delegation, 3+ tools | D | M | low | P3-01 | Realism bar met |
| TRZ-P3-04 | Demo LLM strategy: recorded-completions fixture mode for CI (VCR-style cassettes) + live mode flag for corpus generation | D | M | med | P3-02,03 | CI runs demos with zero API cost |
| TRZ-P3-05 | Nightly corpus job: run both demos (live mode, cheap models), archive run_ids to `benchmark/corpus/index.json` | D | S | low | P3-04 | 7 days of runs accumulated before P5 close |
| TRZ-P3-06 | Adapter version matrix in nightly (min/latest LangGraph + CrewAI) | A | S | low | P3-01 | Matrix red on breakage, links to pinned range |
