# trazo.integrations.crewai (TRZ-P3-01)

`instrument(crew)` wraps a CrewAI `Crew` so its run/step lifecycle and
LLM/tool/memory/delegation boundaries are captured through `Recorder`.
Install with the `crewai` extra: `pip install trazo[crewai]`. Verified
against `crewai==1.15.6` (the pinned range in `pyproject.toml`).

## How it hooks (why, not just what)

Everything is derived from CrewAI's own event bus (`crewai.events`,
`crewai_event_bus`) — no monkeypatching, no text-parsing of console
output. Unlike LangChain's callback system, this bus is a process-wide
singleton with explicit `on`/`off` registration and every event already
carries `task_id`/`task_name`/`agent_id`/`agent_role` directly, so unlike
the LangGraph adapter there's no `parent_run_id`-walking needed to find
the enclosing step — a dict keyed by `task_id` is enough.

- **Step boundaries** (`step.started`/`step.finished`): `TaskStartedEvent`
  / `TaskCompletedEvent`/`TaskFailedEvent`. `state_before`/`state_after`
  snapshot the task's `context` string and its `TaskOutput`, respectively
  — CrewAI has no LangGraph-style explicit channel state to hash instead.
- **LLM boundaries** (`llm.call`): `LLMCallStartedEvent`/
  `LLMCallCompletedEvent`, paired via the `call_id` field they share.
- **Tool boundaries** (`tool.call`): `ToolUsageStartedEvent`/
  `ToolUsageFinishedEvent`. These carry no shared correlation id; CrewAI's
  agent executor runs one tool call at a time per task (true for both the
  native-function-calling and classic ReAct-text-parsing paths, which are
  both synchronous), so a FIFO queue keyed by `task_id` pairs them
  correctly.
- **Delegation** (`agent.message`): delegation and "ask a coworker" are
  *not* separate CrewAI event types — they're implemented as tools
  (`crewai.tools.agent_tools.DelegateWorkTool`/`AskQuestionTool`). Their
  tool name arrives **sanitized** (`crewai.utilities.string_utils
  .sanitize_tool_name`, e.g. `"Delegate work to coworker"` →
  `"delegate_work_to_coworker"` — verified empirically, not the display
  name), so this adapter matches against the sanitized form computed from
  the same function, not a hardcoded guess.
- **Memory boundaries** (`memory.read`/`memory.write`):
  `MemoryQuery*Event`/`MemorySave*Event`.
- **Fingerprints and state hashes** go through the shared
  `trazo.core.fingerprint`/`trazo.core.serialization` — never
  reimplemented here (the latter was hoisted out of the LangGraph adapter
  in this same task, since none of it was LangGraph-specific).

## The event-ordering hazard (the reason this adapter buffers-then-replays)

`crewai_event_bus.emit()` is fire-and-forget: it submits the event to a
10-worker `ThreadPoolExecutor` and returns immediately without waiting,
and CrewAI's own emitters (e.g. `BaseLLM._handle_tool_execution`) never
wait on the returned `Future` either. With more than one worker, handler
**execution** order does not reliably match emission order — this was
caught by a genuinely flaky boundary-coverage test (the first `llm.call`
of a run occasionally landed *after* its own `tool.call`), not by
inspection. The only field that reliably reflects true emission order is
`event.emission_sequence`, assigned synchronously on the emitting thread
before the event is ever handed to the pool.

So `listener.CrewEventCapture` doesn't process events as they arrive:
every registered handler just appends its event to a lock-protected
buffer. `InstrumentedCrew.kickoff()` calls, in order: the crew's real
`kickoff()`; `crewai_event_bus.flush()` (CrewAI's own documented "block
until all pending handlers complete" mechanism); `capture.unregister()`;
`capture.process()`, which sorts the buffer by `emission_sequence` and
replays it through the real per-kind handling in one single-threaded
pass. Only after that is `run.finished`'s totals computed and emitted.
Skipping `flush()` (or processing events live, un-buffered) reproduces
the flaky drop/reorder within a handful of runs.

## Known limitations (Phase 3 scope; tracked, not hidden)

- **`Process.sequential` only.** `Process.hierarchical`'s manager-agent
  orchestration isn't specifically exercised yet.
- **`side_effect_class` defaults to `"external"`** for every tool call —
  same conservative-default rationale as the LangGraph adapter; CrewAI's
  `BaseTool` doesn't declare one either. Escape hatch: `@trace_tool
  (side_effect_class=...)` (TRZ-P2-05).
- **`cost_usd` is always `0.0`.** Same known gap as the LangGraph adapter
  — needs a per-provider pricing table.
- **`provider` is a best-effort guess from the model name string**
  (`gpt-*`/`o1`/`o3` → openai, `claude*` → anthropic, `gemini*` → google,
  else `"unknown"`) — `LLMCallStartedEvent` doesn't carry a provider field.
- **Delegation is recorded as one `agent.message`**, not two (an outbound
  delegation plus an inbound result). CrewAI's delegation is a single
  synchronous tool call, not two hops in its own event model, so this
  matches what's actually observable rather than inventing a second event.
- **`store` is always `"vector"`** for memory events — CrewAI's default
  memory backend, and `MemoryBaseEvent` doesn't reliably expose which of
  short-term/long-term/entity/external memory triggered the operation.
- **Memory event pairing (`memory.read`/`memory.write`) hasn't been
  exercised against a live, embedding-backed memory crew** in this
  environment (CrewAI's default embedder needs network access to fetch an
  embedding model) — the mapping is unit-tested directly against
  `crewai.events.types.memory_events`'s documented field shapes instead
  (`tests/test_crewai_listener_memory.py`), not guessed.
