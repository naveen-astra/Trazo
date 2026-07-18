# Trazo — Glossary

Canonical vocabulary. Docs, code identifiers, and UI copy use these terms
exactly; introducing a synonym for an existing concept is a review reject.

| Term | Definition |
|---|---|
| **Run** | One end-to-end execution of an instrumented agent system. Identified by `run_id`. Bounded by `run.started` / `run.finished`. |
| **Event** | The atomic unit of trace data; one envelope (EVENTS.md §1). Identity `(run_id, seq)`. |
| **Step** | A framework-level execution unit (LangGraph node execution, CrewAI task). Carries state snapshots + hashes. |
| **Boundary** | A non-deterministic operation crossing out of agent control flow: `llm.call`, `tool.call`, `memory.read`, `human.checkpoint`. The replay-critical set. |
| **Fingerprint** | sha256 of the canonicalized, normalized inputs of a boundary call. Computed identically at record and replay time by `trazo.core.fingerprint`. |
| **State hash** | sha256 of canonicalized framework state at a step edge. Ground truth for replay fidelity. |
| **Recorder** | SDK component that executes-and-records boundaries (record mode) or substitutes recorded results (replay mode). One code path, two modes. |
| **Adapter** | Framework-specific integration (`trazo.integrations.*`) mapping a framework's hooks onto the capture points in SDK.md §3. |
| **Replay** | Re-driving real agent control flow while satisfying every boundary from recorded history. Never regeneration (ADR-004). |
| **Substituter** | Replay-mode matcher: per-kind cursors over recorded boundary events, exact + K-lookahead fingerprint matching. |
| **Divergence** | A live boundary request during replay that recorded history cannot answer. Strict mode raises `ReplayDivergence`; lenient mode records and continues. |
| **Fidelity** | Measured replay quality: boundary fidelity (matched/total boundaries) and state fidelity (matching state hashes/total steps). |
| **Replay bundle** | Immutable NDJSON export of a run (manifest + ordered events + blob refs) consumed by the replay driver. |
| **Blob** | Content-addressed (sha256) payload stored outside the event row when > inline threshold. |
| **Detector** | Pure function `(event, window) → Detection?` implementing one failure class (AI_DEBUGGER.md). |
| **Detection** | A raised failure finding (`detection.raised` event + projection row) with evidence event refs. |
| **Window / RunWindow** | Per-run in-memory sliding state a detector reads (recent boundaries, state hashes, cost totals). |
| **Injection / chaos harness** | Controlled fault introduction into demo agents producing ground-truth-labeled failure runs. |
| **Policy** | An OPA rule set evaluated against a pending action; decisions: `allow`, `deny`, `escalate`. |
| **Governed action** | A boundary requiring a synchronous policy check before execution (default: `tool.call` with `side_effect_class ∈ {write, external}`). |
| **Projection** | Query-optimized table (`detections`, `policy_decisions`) derived from the authoritative event stream; rebuildable. |
| **Rollup** | Aggregates on `runs.totals` maintained by the store worker. |
| **Lane** | An ownership boundary for parallel contribution (IMPLEMENTATION_PLAN §3). |
| **Spool** | SDK disk buffer for events that could not be shipped; drained on next opportunity. |
| **Corpus** | The versioned set of recorded demo runs (clean + injected) used by benchmarks. |
| **Checkpoint (phase)** | The smoke-script gate that closes a phase. Distinct from `human.checkpoint`, the event kind for human-in-the-loop input. |
