# Phase 5 — Failure injection + anomaly detection (weeks 8–10)

Goal: the labeled failure corpus exists; detectors are implemented and
scored honestly.
Checkpoint: `phase5.sh` — chaos harness generates one run per failure
class with embedded ground truth; offline scorer reports per-class P/R and
clean-run FPR from the corpus; live path raises `detection.raised` visible
over SSE during an injected-loop run.

| ID | Task | Lane | Size | Risk | Deps | DoD |
|---|---|---|---|---|---|---|
| TRZ-P5-01 | Chaos harness `demos/chaos/`: loop/budget/thrash/drift injectors wrapping both demo agents; ground-truth tags in `run.started` | D | L | med | P3-02,03 | Each injector reliably reproduces its class (manual review of 3 runs each) |
| TRZ-P5-02 | Corpus build: ≥25 runs/class + ≥50 clean, both frameworks, hold-out split manifest | D | M | low | P5-01 | `benchmark/corpus/` manifests committed (run refs, not payloads) |
| TRZ-P5-03 | Detector framework: `Detector` protocol, `RunWindow` (ring buffers, state-hash tracking, cost totals, restart rebuild), detector worker wiring bus→detections | A | M | med | P1-06 | Restart rebuild test; pure-function contract enforced by lint rule (no I/O imports in detectors pkg) |
| TRZ-P5-04 | LoopDetector + BudgetDetector + ThrashDetector per AI_DEBUGGER §2 defaults | A | M | med | P5-03 | Unit tests from synthetic streams; thresholds config-driven |
| TRZ-P5-05 | Offline scorer `benchmark/detection/`: same detectors over recorded streams, P/R/FPR/latency per class, tune-on-holdout workflow | D | M | med | P5-02,04 | RQ2 table regenerates by one command; tuned thresholds PR'd back as defaults |
| TRZ-P5-06 | Detection surfacing: `detection.raised` → projections, `GET /runs/{id}/detections`, dashboard badges + evidence deep-links | A+C | M | low | P5-03 | Badge appears live during injected-loop smoke |
| TRZ-P5-07 | (Stretch) Drift classifier: Ollama qwen2.5 temp-0 schema-forced, same Detector protocol, scored on drift corpus w/ 3-seed report | A | L | high | P5-05 | Only merges if FPR ≤ 0.05 holds; else parked with numbers in an issue |
