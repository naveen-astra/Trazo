# trazo.integrations.langgraph (TRZ-P2-04)

`instrument(compiled_graph)` wraps a compiled LangGraph graph so its
run/step lifecycle and LLM/tool boundaries are captured through
`Recorder`. Install with the `langgraph` extra: `pip install
trazo[langgraph]`. Supports `langgraph>=1.2.3,<2`; the minimum and the
latest release are both tested nightly (TRZ-P3-06).

The floor is set by security, not features: every release below 1.0.10
carries open advisories, and 1.0.10–1.2.2 cannot reach a patched
`langgraph-sdk`. The extra also pins the first patched
`langgraph-checkpoint` (4.1.1) and `langgraph-sdk` (0.4.4) directly,
because LangGraph's own ranges still admit vulnerable versions. It pins
`langchain-core>=1.4` too, which `trazo.core.serialization` needs for
pydantic-v2 message classes. See `pyproject.toml` for the details.

### Upgrading from LangGraph 0.2

LangGraph 1.x passes `config` to a node only if the parameter is
unannotated or typed `RunnableConfig`. A node written as
`def node(state, config: dict[str, Any])` now fails with
`missing 1 required positional argument: 'config'`. This is LangGraph's
change, not Trazo's — fix it in your graph:

```python
from langchain_core.runnables import RunnableConfig


def node(state: MyState, config: RunnableConfig) -> dict[str, Any]: ...
```

## How it hooks (why, not just what)

Everything is derived from LangChain's callback system
(`config={"callbacks": [...]}`) — no monkeypatching, no `stream_mode`
polling:

- **Step boundaries** (`step.started`/`step.finished`): LangGraph tags
  each node's own wrapper chain with `metadata["langgraph_node"]`; that
  wrapper's `on_chain_start` `inputs` / `on_chain_end` `outputs` are
  exactly the full graph state before/after the node ran — verified
  empirically, not assumed. LangGraph wraps a node in more than one
  nested chain carrying the *same* metadata; only the outermost one (the
  one whose parent isn't already a tracked step) is treated as the
  boundary, so a node isn't double-recorded.
- **LLM/tool boundaries**: `on_chat_model_start`/`on_llm_end` and
  `on_tool_start`/`on_tool_end`. Attribution to the enclosing step walks
  `parent_run_id` up through every run the handler has seen, rather than
  relying on contextvars persisting across separate callback invocations
  (they don't reliably — separate callbacks are separate calls, not
  nested frames of one call stack).
- **Fingerprints and state hashes** go through the shared
  `trazo.core.fingerprint`/`state_serializer` — never reimplemented here.

## Known limitations (Phase 2 scope; tracked, not hidden)

- **`.invoke()` only.** `.stream()`/`.astream()` pass-through
  instrumentation is later work — TASKS/PHASE_2.md scopes P2-04 to
  `instrument(graph)` without specifying streaming.
- **`side_effect_class` defaults to `"external"`** for every tool call.
  LangChain's tool-call callbacks don't expose enough metadata to
  classify a tool as `read`/`write`/`external` automatically; `external`
  is the conservative default (policy defaults are stricter for
  `write`/`external`, EVENTS.md §2.3). A tool that wants a different
  classification should use the `@trace_tool(side_effect_class=...)`
  escape hatch (TRZ-P2-05) instead of relying on this adapter.
- **`cost_usd` is always `0.0`.** Needs a per-provider pricing table this
  task didn't build; tracked as a follow-up, not silently wrong-but-hidden.
- **`provider` is the model class's Python name** (e.g. `ChatOpenAI`), not
  a normalized string like `openai` — LangChain's callback `serialized`
  payload doesn't carry a normalized provider id.
- **Single-threaded, synchronous graphs only.** Parallel LangGraph
  branches are handled correctly for step/state capture (each gets its
  own tracked step via its own `run_id`), but this hasn't been exercised
  against `ainvoke`/async node functions.
