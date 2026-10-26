# Goal-drift judge (opt-in), scored on the failure corpus

Judge model: `qwen2.5:3b` at `http://localhost:11434/v1`; judging every 2 model calls, raising after 2 consecutive off-task verdicts, at most once per run. Scored 2026-10-26. Regenerate with `uv run --project sdk python benchmark/detection/drift_runner.py --model <model> --skip-first 8`.

The first 8 runs of each (project, label) group are the development set the prompt was tuned on and are excluded here.

A model's verdicts are not deterministic across models, versions or hardware: treat these as one measurement of one model, not a property of the detector. The rule detectors' numbers (`results.md`) are reproducible; these are not guaranteed to be.

| Slice | Drift runs | Caught | Missed | False alarms | Precision | Recall | FPR (clean) |
|---|---|---|---|---|---|---|---|
| all | 34 | 34 | 0 | 135 | 20% | 100% | 100% |
| content-pipeline | 17 | 17 | 0 | 93 | 15% | 100% | 100% |
| research-assistant | 17 | 17 | 0 | 42 | 29% | 100% | 100% |

**Verdict: do not use this judge.** It raised drift on 100% of clean runs, so its catches of real drift say nothing: it does not separate drifted runs from healthy ones. Try a stronger model.

Drift judge firing, by corpus label:

| Label | Runs | Judge raised drift |
|---|---|---|
| budget | 34 | 17 |
| clean | 84 | 84 |
| drift | 34 | 34 |
| loop | 34 | 17 |
| thrash | 34 | 17 |

Median detection latency after the drift began: 3 events.

Judging cost: median 1.7s per run on the scoring machine.
