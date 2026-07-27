# content-pipeline (TRZ-P3-03)

A CrewAI crew: Researcher / Writer / Editor, 15 tasks, one delegation, 5
tool calls. Demonstrates the SDK's public API only (`trazo.init`,
`instrument`, `trazo.shutdown`) — per IMPLEMENTATION_PLAN.md's lane table,
`demos/` never imports `trazo.core` directly. Unlike the research-assistant
(LangGraph) demo, the tools here are plain CrewAI tools (`crewai.tools
.tool`), not wrapped with `@trace_tool`: CrewAI's own agent executor
already emits `ToolUsageStartedEvent`/`ToolUsageFinishedEvent` for any
tool an agent calls, and TRZ-P3-01's adapter already captures those — no
escape hatch needed (the LangGraph demo needed one only for memory
operations, which no adapter auto-captures).

## Run it

```bash
uv run --project sdk --extra crewai python demos/content-pipeline/run.py \
    --endpoint http://localhost:8420
```

Needs a live control plane at `--endpoint` (default `http://localhost:8420`,
env `TRAZO_ENDPOINT`) to actually ingest the trace; without one the SDK
spools events to `.trazo/spool/*.ndjson` instead of failing.

## Why it's deterministic (no LLM API key needed)

`llm.py`'s `ScriptedLLM` is rule-based, not a real model — same rationale
as the research-assistant demo: zero API cost in CI (TRZ-P3-04), and every
call still goes through CrewAI's real event-emission path, so it's
recorded as a genuine `llm.call`/`tool.call` with a real fingerprint.
Since one CrewAI `Agent` reuses the same `llm` across every task it
executes (unlike the LangGraph demo's one-function-per-node design),
`ScriptedLLM` looks up its canned response by a `[tag]` embedded in each
task's own `description` — CrewAI's prompt template includes it verbatim
as `"Current Task: {description}"` (confirmed empirically) — rather than
tracking one linear step counter.

## Realism bar (Phase 3 checkpoint)

CrewAI's `step` is one `Task` (TRZ-P3-01's adapter maps
`TaskStartedEvent`/`TaskCompletedEvent` to `step.started`/`step.finished`
regardless of how many LLM/tool rounds happen inside it) — hitting "≥15
steps" here means 15 actual `Task` objects (4 research + 6 writing + 5
editing), not 15 LLM turns. Verified by running it and inspecting the
spooled trace (five consecutive clean runs):

| Metric | Bar | This run |
|---|---|---|
| Steps (`step.started`) | ≥ 15 | 15 |
| Agents/roles (distinct `agent_id`) | ≥ 2 | 3 (Researcher, Writer, Editor) |
| Tool calls | ≥ 5 | 5 (4× `web_search`, 1× `word_count`) |
| Delegation | — | 1 (`agent.message`, Writer → Researcher) |

Memory events aren't produced by this crew — the research-assistant demo
already covers "memory events present" for the Phase 3 corpus, and this
demo's own task description doesn't mention memory.

## Two real bugs this demo found

- **Delegation builds an ad-hoc task with no `[tag]`.** CrewAI's
  `Delegate work to coworker` tool constructs a brand-new task description
  from whatever the delegating agent's `Action Input` says — it's never
  one of this module's own 15 declared `Task` objects, so `ScriptedLLM`
  falls back to a generic confirmation reply instead of a `KeyError`.
- **`shutdown(timeout=10.0)` wasn't always enough.** Against an
  unreachable endpoint, each failed POST attempt can itself take several
  seconds, and one flush cycle can need two of them (drain the previous
  failed batch, then post the new one) — losing this demo's largest batch
  when the 10-second join timed out mid-POST, silently killing the daemon
  Shipper thread. Bumped to 30s in `run.py` (and in the research-assistant
  demo, which has the same underlying exposure).
