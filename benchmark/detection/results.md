# RQ2 — Detector precision/recall (TRZ-P5-05)

Regenerate with `uv run --project sdk python benchmark/detection/runner.py`.

| Class | Corpus | TP | FN | FP | Precision | Recall | FPR (clean) | Median latency (events) |
|---|---|---|---|---|---|---|---|---|
| loop | 50 | 50 | 0 | 25 | 67% | 100% | 0% | 15.0 |
| budget | 50 | 50 | 0 | 0 | 100% | 100% | 0% | 21.0 |
| thrash | 50 | 25 | 25 | 0 | 100% | 50% | 0% | n/a |

Clean corpus: 100 runs. Drift corpus: 50 runs — no rule detector targets drift (AI_DEBUGGER.md §5's stretch classifier, TRZ-P5-07); reported as corpus size only.

## RQ3 — Baseline comparison (flag-any-fault)

RandomFlaggerAdapter has no notion of loop/budget/thrash classes -- only "did this tool flag anything in this run" -- so it's compared against Trazo's own detectors at that same binary level, not per-class, to anchor the scale (RESEARCH.md RQ3).

| Adapter | Corpus (faulty) | TP | FN | FP | Precision | Recall | FPR (clean) |
|---|---|---|---|---|---|---|---|
| trazo (loop+budget+thrash) | 200 | 125 | 75 | 0 | 100% | 62% | 0% |
| random_flagger (baseline) | 200 | 164 | 36 | 67 | 71% | 82% | 67% |
