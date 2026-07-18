# Trazo — Research Program

Three research questions, each with a defined experiment, metrics, and an
artifact that survives independently of Trazo's success. Papers target
workshop-length first (honest for a semester), extensible later.

## RQ1 — Deterministic replay for non-deterministic multi-agent systems

**Question.** Can step-by-step replay of agent runs be made reliable via
checkpointed state + recorded boundary I/O, generalizing across frameworks
rather than bespoke to one?

**Experiment.** Corpus: all demo-agent runs (clean + injected, both
frameworks; target ≥ 150 runs). For each: strict-mode replay on unchanged
code → boundary fidelity, state fidelity, replay overhead
(REPLAY_ENGINE §5). Then controlled mutations (prompt tweak, tool-arg
change, framework minor-version bump) → measure divergence detection
quality: is the *first* divergence reported at the true first point of
change (localization accuracy)?

**Metrics.** State-fidelity rate (headline, target ≥ 0.99 unchanged);
divergence localization accuracy (target ≥ 0.9 within ±1 boundary);
replay overhead ratio (target ≤ 0.25).

**Artifact.** The replay contract (REPLAY_ENGINE.md) + fidelity harness
(`benchmark/fidelity/`) + numbers table, all regenerable by one script.

**Venue shape.** MLSys-style systems paper or NeurIPS/ICML agents
workshop.

## RQ2 — A failure taxonomy and detection framework for agentic workflows

**Question.** What are the recurring failure signatures of multi-agent
execution, and can a lightweight rules(-plus-small-LLM) detector catch
them with production-acceptable false-positive rates?

**Experiment.** Taxonomy v1 (loop, budget runaway, thrash, drift —
AI_DEBUGGER §1) instantiated as an injected, ground-truth-labeled corpus
(≥ 25 runs/class + ≥ 50 clean; hold-out split for threshold tuning vs.
reporting). Detectors run offline over recorded streams
(AI_DEBUGGER §3). Stretch: drift classifier at temp-0 with schema-forced
JSON, three seeds reported to expose residual nondeterminism.

**Metrics.** Per-class precision/recall (targets ≥ 0.9 / ≥ 0.85);
clean-run FPR (≤ 0.05, first-class number, not a footnote); detection
latency in events after onset.

**Artifact.** The labeled corpus + taxonomy definitions + scoring harness
(`benchmark/detection/`) — reusable by anyone building detectors,
independent of Trazo.

**Venue shape.** Agents/safety workshop (NeurIPS Agents, ICML reliable-ML).

## RQ3 — An open benchmark for agent-observability tooling

**Question.** How should the field evaluate tools like this at all?

**Experiment/artifact.** Package RQ1+RQ2 corpora and scoring into
**TrazoBench v0**: failure-injected traces across two frameworks (three
post-MVP), ground truth, metric definitions, a runner that scores any tool
exposing a small adapter interface (`detect(events) -> detections`,
`replay(bundle) -> report`). Baselines: Trazo's own numbers + a trivial
baseline (random flagger) to anchor the scale. Publish as versioned data +
code release.

**Venue shape.** NeurIPS Datasets & Benchmarks (full) or workshop (v0).

## Threats to validity (tracked honestly in all three)

Injected failures may not distribute like organic production failures
(mitigation: taxonomy sourced from documented incident reports, cited);
two frameworks limit generality claims (mitigation: claim scoped, AutoGen
on roadmap); self-benchmarking bias in RQ3 (mitigation: adapter interface
+ third-party-runnable release).

## Timeline coupling

RQ1 numbers exist at P4 close; RQ2 at P5 close; RQ3 assembly is P7.
Writing happens after P7 — the semester deliverable is the *reproducible
numbers*, not the prose.
