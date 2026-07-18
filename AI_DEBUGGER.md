# Trazo — Anomaly Detection (the AI debugger)

The meta-agent that watches other agents. MVP is deliberately
measurement-first: three rule-based detectors with published
precision/recall against injected failures. The LLM classifier for goal
drift is a stretch goal *inside* the same interface, so adding it never
touches the pipeline.

---

## 1. Failure taxonomy (v1 — the research artifact)

| Class | Signature | Detector type |
|---|---|---|
| **Loop** | Same tool called with identical/near-identical fingerprint ≥ N times within a window without state-hash progress | Rule |
| **Budget runaway** | Cumulative `cost_usd` or token totals exceed configured budget, or cost *velocity* (Δcost/Δsteps) exceeds rate cap | Rule |
| **Tool thrash** | ≥ N distinct tools invoked with no `step.finished` state-hash change across M steps (busy, no progress) | Rule |
| **Goal drift** | Semantic divergence between `run.started.entry_input` intent and recent step/plan content | LLM classifier (stretch) |

The taxonomy definitions, injection methods, and labeled corpus are a
deliverable independent of the detectors (RESEARCH.md RQ2).

## 2. Detector architecture

```
EventBus ─▶ DetectorWorker
              │ per-run WindowState (ring buffers: recent boundary events,
              │ state hashes, cost totals) — in-memory, rebuilt from store on restart
              ├─ LoopDetector.on_event(e, window)      → Detection?
              ├─ BudgetDetector.on_event(e, window)    → Detection?
              ├─ ThrashDetector.on_event(e, window)    → Detection?
              └─ DriftClassifier.on_step(e, window)    → Detection?   [stretch]
                     └── Ollama (qwen2.5) with strict JSON schema output
Detection ─▶ detection.raised event ─▶ bus ─▶ store + SSE + policy context
```

Contract (`trazo_server.detectors.base.Detector`):

```python
class Detector(Protocol):
    id: str                       # "loop" | "budget" | ...
    def on_event(self, event: Envelope, window: RunWindow) -> Detection | None: ...
```

Rules for detector implementations:

- Pure functions of `(event, window)` — no I/O, no store access. Anything a
  detector needs must be derivable from the stream (this is what makes them
  benchmarkable offline against recorded traces).
- Deterministic: same event sequence → same detections. The LLM classifier
  is the sanctioned exception; it runs at temperature 0 with schema-forced
  output and its nondeterminism is measured, not hidden (RESEARCH.md).
- Config via `TRAZO_DETECT_*` env (thresholds N, M, windows, budgets), with
  defaults documented here and tuned against the injected-failure corpus.

Default thresholds (starting points, to be tuned in Phase 5):
loop: N=5 identical fingerprints / 20 events with no state change;
budget: absolute from policy config, velocity 3× trailing mean;
thrash: 4+ distinct tools across 6 steps with unchanged state hash.

## 3. Offline mode (benchmark harness)

`benchmark/detection/runner.py` feeds recorded event streams (from the
failure-injection corpus) through the same detector code — no bus, no
worker — and scores detections against ground-truth labels embedded by the
injection harness (`tags.injected_failure = {class, start_seq}`). Metrics:
per-class precision, recall, false-positive rate on clean runs, median
detection latency in events (how many events after injection onset until
raised). Same code online and offline is the point — no benchmark-only
detector forks.

## 4. Failure-injection harness (`demos/chaos/`)

Injectors wrap demo agents with controlled faults:

- `loop`: patch a tool to return a "try again" style response driving the
  planner to reissue the call.
- `budget`: inflate reported `cost_usd`/token counts by a factor mid-run.
- `thrash`: corrupt tool results so no tool satisfies the planner's check.
- `drift`: adversarial mid-run prompt injection redirecting the objective
  (labeled corpus for the stretch classifier and for RQ2 regardless).

Each injected run is tagged with ground truth in `run.started.tags`. The
corpus target: ≥ 25 runs/class injected + ≥ 50 clean runs across both demo
agents.

## 5. Why not LLM-first detection

Rules are cheap, deterministic, explainable, and cover 3/4 classes with
measurable quality — the right MVP trade. The drift classifier exists
because drift genuinely isn't rule-expressible; it stays a stretch because
the benchmark must not depend on a 7B model's mood. If it lands, it's
evaluated with the same harness and reported with its own FPR. (Philosophy
#7: novelty budget spent on taxonomy + measurement, not on "agent watches
agent" theater.)
