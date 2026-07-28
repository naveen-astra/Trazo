# research-assistant (TRZ-P3-02)

A LangGraph agent: `plan -> search -> retrieve -> synthesize -> evaluate`,
looping until enough findings are gathered, then `finalize`. Demonstrates
the SDK's public API only (`trazo.init`, `instrument`, `trace_tool`,
`trace_llm`, `trace_memory_read`/`trace_memory_write`, `trazo.shutdown`) —
per IMPLEMENTATION_PLAN.md's lane table, `demos/` never imports
`trazo.core` directly.

## Run it

```bash
uv run --project sdk --extra langgraph --extra demos \
    python demos/research-assistant/run.py \
    --question "what is trazo" --endpoint http://localhost:8420
```

Needs a live control plane at `--endpoint` (default `http://localhost:8420`,
env `TRAZO_ENDPOINT`) to actually ingest the trace; without one the SDK
spools events to `.trazo/spool/*.ndjson` instead of failing (Shipper's
documented failure mode) — useful for inspecting a run's shape offline.

## Why it's deterministic by default (no LLM API key needed)

`llm.py`'s `ask_*` functions are rule-based, not calls to a real model —
TRZ-P3-02's own DoD wants "deterministic-ish fixture inputs", and every
demo must run in CI with zero API cost. Each `ask_*` call still goes
through the real `@trace_llm` decorator, so it's recorded as a genuine
`llm.call` event with a real fingerprint — `trace_llm` doesn't know or
care how the wrapped function produced its answer.

`--live` (TRZ-P3-04) calls a real model instead — needs
`TRAZO_DEMO_API_KEY` or `OPENAI_API_KEY` — and records the exchange to
`cassette.json`, which fixture mode then replays on later runs before
ever falling back to the rule-based stub. See `demos/_shared/README.md`
for the cassette mechanics; this is what the nightly corpus job
(TRZ-P3-05) uses to generate fresh traces without paying for every CI
run too.

## Vector memory

`memory.py` uses real chromadb, but with a small custom hash-based
embedding function instead of chromadb's default: the default downloads a
~79MB ONNX model from HuggingFace on first use, which fails (or hangs)
with no network access — exactly what TRZ-P3-04's "zero API cost" demo
constraint rules out. The hash embedding is deterministic (same text
always maps to the same vector) and good enough to make related findings
score closer than unrelated ones for this demo's small, fixed vocabulary —
not a claim of real semantic search quality.

## Realism bar (Phase 3 checkpoint)

With the default `--target-iterations 3`, one run produces (verified by
running it and inspecting the spooled trace, six consecutive clean runs):

| Metric | Bar | This run |
|---|---|---|
| Steps (`step.started`) | ≥ 15 | 16 (5 nodes × 3 iterations + 1 finalize) |
| Agents/roles (distinct `agent_id`) | ≥ 2 | 6 (one per node name) |
| Tool calls | ≥ 5 | 5 (3× `web_search`, 1× `fetch_document`, 1× `calculator`) |
| Memory events | present | 6 (3× `memory.read`, 3× `memory.write`) |

## A real bug this demo found

Relying on `atexit` alone (no explicit flush before the process exits)
left most of a run's events stuck in the Shipper's queue — confirmed by
running this exact demo and inspecting the spool. `Recorder.shutdown()`
already documented this ("call explicitly for a deterministic flush in
short-lived processes"), but there was no public equivalent for a
`demos/`-lane script to call without reaching into `trazo.core`. Fixed by
adding `trazo.shutdown()` to the public API (`sdk/src/trazo/__init__.py`)
and calling it from `run.py`'s `finally` block.
