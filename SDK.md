# Trazo — SDK Architecture

Package `trazo` (Python ≥ 3.10). The SDK is the only code that runs inside
a user's process; its prime directives, in order: (1) never crash or slow
the host agent beyond budget, (2) capture every boundary faithfully,
(3) make replay possible. Public API surface is deliberately tiny.

---

## 1. Public API (all of it)

```python
import trazo

trazo.init(project="research-assistant", endpoint=..., api_key=...)  # once

from trazo.integrations.langgraph import instrument
traced_graph = instrument(graph)                  # LangGraph
from trazo.integrations.crewai import instrument
traced_crew = instrument(crew)                    # CrewAI

from trazo import replay
session = replay.load("run_01J...", mode="strict")
trazo.replay.entrypoint(build_fn)                 # register for full-run replay

# escape hatch for custom agents / un-adapted boundaries:
from trazo import trace_tool, trace_llm
@trace_tool(side_effect_class="external")
def web_search(q: str) -> str: ...
```

Everything else is internal (`trazo._internal` naming not used — modules
under `trazo.core` are documented as internal-stable for adapter authors).

## 2. Internal architecture

```
adapter (langgraph/crewai)          # framework-specific interception
   │  normalized boundary calls
   ▼
Recorder ── mode=RECORD ──▶ EventBuffer ─▶ Shipper (bg thread, batch POST)
   │                                          │ failure ▶ DiskSpool ▶ retry
   └─ mode=REPLAY ──▶ Substituter (cursor match against loaded bundle)
Context (contextvars): run_id, step stack, seq counter, agent_id
PolicyHook: sync check before governed actions (see ADR-006)
Fingerprint: canonical normalization + sha256 (shared with replay)
Redactor: key-pattern scrub before buffering
```

- **Recorder** is mode-switched, not duplicated: adapters call
  `boundary(kind, inputs, execute_fn)` and the recorder either executes +
  records (record mode) or substitutes (replay mode). One code path for
  interception logic guarantees record/replay symmetry.
- **Shipper** is a daemon thread; flush triggers: 200 events, 1 MB, or
  500 ms, whichever first. `atexit` + `run.finished` force a final flush.
- **DiskSpool** (`.trazo/spool/*.ndjson`): written on ship failure; a
  spool drain attempt precedes every new ship. Drop-with-warning only when
  spool exceeds `TRAZO_SPOOL_MAX_MB` (default 256).
- **Overhead budget**: ≤ 10% wall-clock. Enforced by a benchmark test in CI
  (demo agent with/without SDK, threshold asserted).

## 3. Adapter contract (what a new adapter must implement)

An adapter is a module exposing `instrument(framework_obj, **cfg)` and
registering these capture points:

| Capture point | Emits | Required |
|---|---|---|
| Run start/end | `run.started` / `run.finished` | yes |
| Framework step boundaries | `step.started` / `step.finished` with state snapshot + hash via a documented `state_serializer` | yes |
| LLM invocation | `llm.call` through `Recorder.boundary` | yes |
| Tool invocation | `tool.call` through `Recorder.boundary` | yes |
| Memory/retrieval | `memory.read` / `memory.write` | yes if framework exposes it |
| Inter-agent messages | `agent.message` | yes if framework has multi-agent semantics |
| Replay determinism aids | seed `random`, freeze time during replay (best-effort) | documented per adapter |

Rules: adapters own *where* to hook (monkeypatch, callback API, middleware —
framework's most stable mechanism, documented in the adapter's README);
`core` owns *what happens* at the hook. An adapter that lets any boundary
bypass `Recorder.boundary` is critically broken (breaks replay silently).
Framework versions are pinned as extras (`trazo[langgraph]`) with a tested
version range in CI.

**LangGraph specifics:** wrap graph via node-level middleware (pre/post
node = step events; state = channel values snapshot); LLM/tool capture via
LangChain callbacks handler scoped to the run context.
**CrewAI specifics:** task execution = steps; agent-to-agent delegation =
`agent.message`; tool wrapping via CrewAI's tool registry.

## 4. Policy hook placement

The adapter calls `PolicyHook.check(action_ctx)` immediately before
executing any `tool.call` with `side_effect_class in {write, external}`
(and any action matching `TRAZO_POLICY_SCOPE` config). Deny → raise
`trazo.PolicyDenied` into user code after emitting the decision event.
`TRAZO_POLICY_MODE=off|observe|enforce`; observe evaluates and records but
never blocks — teams turn on enforce after reviewing observe logs.

## 5. CLI

`trazo tail <run_id>` (SSE client), `trazo replay <run_id> [--step N]
[--mode strict|lenient]`, `trazo verify <run_id>` (fidelity report),
`trazo doctor` (connectivity, spool status, version skew).

## 6. Testing strategy (SDK-specific)

- Unit: recorder mode symmetry (record then replay same script → zero
  divergence), fingerprint canonicalization golden files, redactor, spool
  crash-recovery (kill -9 mid-run, spool drains on next init).
- Integration: real LangGraph + CrewAI toy agents in CI, full record →
  ingest → bundle → replay → verify loop against a compose stack.
- Property: fingerprint stability under dict ordering / unicode forms
  (hypothesis).
