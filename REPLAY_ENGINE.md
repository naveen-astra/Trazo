# Trazo — Replay Engine Design

The core technical bet. This document defines exactly what replay means,
how substitution works, what divergence is, and how fidelity is measured.
Anything demoed as "replay" that does not follow this document is fake and
gets reverted.

---

## 1. Semantics (ADR-004)

**Replay re-drives the agent's real control flow; the outside world does
not run again.** During a recorded run, every non-deterministic boundary
(`llm.call`, `tool.call`, `memory.read`, `human.checkpoint`) was captured
with a fingerprint of its inputs and its full result. During replay, the
same agent code executes again, but when it reaches a boundary, the SDK
intercepts the call, matches it against the recorded event, and returns the
**recorded** result instead of issuing a live call.

What this gives you: a faithful, steppable reconstruction of what the agent
saw and decided at every step of one specific historical run.
What it does not give you: prediction of a fresh run. We never claim that.

Precedent: Temporal's workflow replay (history substitution for Activities).
We are applying the same contract to agent frameworks.

## 2. Matching model

Recorded boundary events for a run form an ordered list per kind:
`B = [(seq, kind, fingerprint, result), ...]`.

Replay maintains a cursor per kind. When the re-driven code hits a boundary:

1. Compute the live fingerprint from the live call's inputs (same
   `trazo.core.fingerprint` code as recording — single implementation).
2. Compare with the recorded event at the cursor:
   - **Exact match** (same kind, same fingerprint): return recorded result;
     advance cursor. The normal case.
   - **Lookahead match** (fingerprint matches one of the next K=3 recorded
     events of that kind): events were recorded from a framework that
     parallelizes; consume out of order, mark `reordered` in the replay
     report. Legal but reported.
   - **Mismatch**: divergence. See §3.
3. Emit a `replay.step` record into the local replay report (never into the
   original run's event stream — replays are read-only over history).

Determinism requirement on adapters: an adapter must route **every**
boundary through the recorder in record mode and through the substituter in
replay mode. A boundary that bypasses interception in either mode is a
correctness bug of the highest severity.

## 3. Divergence

Divergence = the re-driven code requested something the history cannot
answer (fingerprint mismatch beyond lookahead, cursor exhausted, or kind
mismatch). Causes: agent code changed since recording; framework version
changed; genuine nondeterminism in user code (e.g. `random()` outside a
boundary, wall-clock branching).

Modes (CLI/config selectable):

| Mode | Behavior on divergence |
|---|---|
| `strict` (default for verification) | Raise `ReplayDivergence` with a structured diff: expected event (seq, kind, fingerprint, input summary) vs. live request; stop. |
| `lenient` (default for interactive debugging) | Record the divergence in the report, return the *recorded-at-cursor* result anyway, continue. Lets you inspect "how far does the old history carry the new code." |

`ReplayDivergence` diffs are first-class UX: they show a field-level JSON
diff of normalized inputs, because "which part of the prompt changed" is
the actual question a debugging engineer has.

## 4. Step API (what the CLI/dashboard build on)

```python
from trazo import replay

session = replay.load("run_01J...", mode="strict")   # fetches replay bundle
for step in session.steps():          # framework steps, ordered
    step.index, step.name
    step.state_before, step.state_after       # recorded snapshots (lazy blob fetch)
    step.boundary_events                      # recorded llm/tool/memory events in step
    step.verify()                             # re-drive just this step, compare state_after_hash
report = session.run_to(step_index=7)         # re-drive from start to step 7
report.fidelity                                # matched / total boundaries
report.divergences                             # []
```

Under the hood `run_to` re-invokes the instrumented agent entrypoint (the
demo agents expose a standard `build()` factory for this; user code
documents its entrypoint via `trazo.replay.entrypoint` registration).
Step-scoped `verify()` uses the recorded `state_before` snapshot as input —
this is why step events carry full state snapshots, not just hashes.

## 5. Fidelity measurement (feeds RESEARCH.md benchmark)

For a run replayed in strict mode with unchanged code:

- **Boundary fidelity** = matched boundary calls / total recorded boundary
  calls. Target ≥ 0.99.
- **State fidelity** = steps where recomputed `state_after_hash` equals
  recorded hash / total steps. Target ≥ 0.99. This is the headline number.
- **Replay overhead** = replay wall-clock / recorded wall-clock (recorded
  latencies are not simulated; replay should be *faster* — overhead here
  measures engine cost, target ≤ 0.25 of original).

`trazo verify <run_id>` computes all three; `benchmark/fidelity/` runs it
across the full demo-run corpus and emits the table used in the paper.

## 6. Known limits (documented, not hidden)

1. **In-process nondeterminism outside boundaries** (user `random()`,
   time-based branches) can diverge replay. Mitigation: adapters seed
   `random`/`numpy` and freeze `time.time` via context during replay
   (best-effort, documented per adapter); divergence reporting makes the
   residual visible rather than silent.
2. **Framework-internal nondeterminism** (e.g. parallel node scheduling) is
   handled by lookahead matching; frameworks with unstable iteration order
   beyond K=3 need adapter-level ordering hooks — tracked per adapter.
3. **Forking replays** ("change step 5's tool result, continue live") is
   explicitly post-MVP; the bundle format already carries everything it
   needs, so it is additive.

## 7. Replay bundle (transport format)

`GET /v1/runs/{id}/replay-bundle` returns NDJSON: line 1 a manifest
(run metadata, event count, blob manifest), then events in `seq` order with
blob refs; blobs fetched lazily via `GET /v1/blobs/{sha256}` and cached in
`.trazo/cache/`. Bundles are immutable and cacheable forever by content.
