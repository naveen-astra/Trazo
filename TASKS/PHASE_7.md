# Phase 7 — Benchmark assembly + release (week 12)

Goal: TrazoBench v0 assembled; v0.1.0 tagged; the MASTER_PLAN §4.3 demo
rehearsed and recorded.
Checkpoint: `phase7.sh` — `make benchmark` regenerates RQ1+RQ2 tables from
corpus manifests; `pip install dist/trazo-*.whl` in a clean venv traces a
toy agent against compose; demo script executes clean.

| ID | Task | Lane | Size | Risk | Deps | DoD |
|---|---|---|---|---|---|---|
| TRZ-P7-01 | TrazoBench packaging: corpus manifests + scoring runners + adapter interface (`detect(events)`, `replay(bundle)`) + random-flagger baseline + versioned data release notes | D | L | med | P4-07, P5-05 | Third-party-runnable per RESEARCH RQ3; baseline numbers in README |
| TRZ-P7-02 | Release engineering: `release.yml` (wheel build, dashboard bundle, compose archive), version stamping, CHANGELOG, `schema-v1.0` cross-check | A | M | low | all phases | Tag → artifacts attached to GitHub Release |
| TRZ-P7-03 | README rewrite: status table flipped to shipped reality, quickstart (15-min time-to-first-trace verified by a timed fresh-machine run), security posture note (ADR-009) | D | M | low | P7-02 | A newcomer executes quickstart unaided |
| TRZ-P7-04 | MVP demo script + rehearsal: MASTER_PLAN §4.3 steps 1–6 as a documented runbook + recorded screencast | D | M | low | P6, P4 | Live run-through twice without intervention |
| TRZ-P7-05 | Handbook audit: every doc's claims match shipped behavior; stale statements fixed or ticketed; debt review (IMPLEMENTATION_PLAN §8) | A+B+C+D | M | low | all | Zero known doc-code contradictions at tag time |
