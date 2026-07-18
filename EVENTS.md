# Trazo — Canonical Event Model

**This is the most load-bearing contract in the system.** Every component is
a producer or consumer of these events. The machine-readable source of truth
is `schema/trace-event.v1.schema.json`; this document explains it. The two
must never disagree — CI enforces that SDK and control-plane models validate
against the schema.

Versioning: the envelope carries `schema: "trazo.v1"`. Additive changes
(new optional fields, new event kinds) are allowed within v1. Renames,
removals, or semantic changes require v2 and an ADR.

---

## 1. Envelope

Every event, regardless of kind, is this envelope:

```jsonc
{
  "schema": "trazo.v1",
  "event_id": "evt_01J...",        // ULID, assigned by SDK
  "run_id": "run_01J...",          // ULID, one per instrumented execution
  "project": "research-assistant", // logical grouping, maps to project_id
  "seq": 42,                       // strictly increasing per run, assigned by SDK
  "ts": "2026-07-18T09:30:00.123Z",// event time, SDK clock
  "kind": "tool.call",             // see §2
  "step_id": "stp_01J...",         // enclosing framework step, if any
  "agent_id": "researcher",        // logical agent within the run, if any
  "parent_event_id": null,         // causal parent (e.g. retry of)
  "fingerprint": "sha256:...",     // §3 — present on boundary events only
  "otel": { "trace_id": "...", "span_id": "..." },  // optional OTel bridge
  "payload": { ... },              // kind-specific, §2
  "blobs": [ {"field": "payload.result", "sha256": "...", "bytes": 183221} ]
}
```

Rules:

- `(run_id, seq)` is the identity. Storage upserts on it; replay orders by it.
- `seq` gaps are legal (dropped events); ordering is authoritative, wall
  clocks are not.
- Any payload field may be **offloaded**: value replaced by
  `{"$blob": "sha256:..."}` and listed in `blobs` when > 32KB inline limit.
- Everything is UTF-8 JSON. Binary tool outputs are base64'd into blobs.

## 2. Event kinds and payloads

### 2.1 Run lifecycle

| kind | payload |
|---|---|
| `run.started` | `framework` (`langgraph`\|`crewai`\|`custom`), `framework_version`, `sdk_version`, `entry_input` (offloadable), `tags` (map), `code_ref` (git sha if detectable) |
| `run.finished` | `status` (`ok`\|`error`\|`blocked`\|`cancelled`), `error` (type, message, stack — on error), `totals` (events, llm_calls, tool_calls, cost_usd, tokens_in, tokens_out, duration_ms) |

### 2.2 Step lifecycle (framework-level units: a LangGraph node execution, a CrewAI task)

| kind | payload |
|---|---|
| `step.started` | `name`, `step_index`, `state_before_hash` (§4), `state_before` (offloadable snapshot) |
| `step.finished` | `status`, `state_after_hash`, `state_after` (offloadable), `duration_ms` |

### 2.3 Non-deterministic boundaries (the replay-critical four; all carry `fingerprint`)

| kind | payload |
|---|---|
| `llm.call` | `provider`, `model`, `params` (temperature etc.), `messages_in` (offloadable), `response` (offloadable), `tokens_in`, `tokens_out`, `cost_usd`, `latency_ms`, `error?` |
| `tool.call` | `tool_name`, `args` (offloadable), `result` (offloadable), `status`, `latency_ms`, `error?`, `side_effect_class` (`read`\|`write`\|`external`) |
| `memory.read` | `store` (`vector`\|`kv`\|`framework`), `query` (offloadable), `results` (offloadable — includes docs/scores for the memory inspector), `k`, `latency_ms` |
| `memory.write` | `store`, `key_or_ns`, `value` (offloadable), `latency_ms` |

`side_effect_class` matters: replay always substitutes; policy defaults are
stricter for `write`/`external`.

### 2.4 Coordination & governance

| kind | payload |
|---|---|
| `agent.message` | `from_agent`, `to_agent`, `content` (offloadable), `message_type` (`handoff`\|`delegation`\|`result`\|`other`) |
| `plan.updated` | `plan` (offloadable), `reason` |
| `human.checkpoint` | `prompt`, `response` (offloadable), `latency_ms` — treated as a boundary (fingerprinted) since it's non-deterministic input |
| `policy.decision` | `policy_id`, `action_ref` (the would-be event's fingerprint + kind), `decision` (`allow`\|`deny`\|`escalate`), `reasons` [], `eval_latency_ms`, `mode` (`observe`\|`enforce`) |
| `detection.raised` | `detector` (`loop`\|`budget`\|`thrash`\|`drift`), `severity` (`info`\|`warn`\|`critical`), `evidence_event_ids` [], `details` (detector-specific), `window` |
| `sdk.diagnostic` | `level`, `message`, `dropped_events?` — the SDK reporting on itself |

## 3. Fingerprints (contract with replay — details in [REPLAY_ENGINE.md](REPLAY_ENGINE.md))

`fingerprint = "sha256:" + sha256(canonical_json(normalized_inputs))` where
`normalized_inputs` is kind-specific: for `llm.call`, `(provider, model,
params minus sampling seed, messages_in)`; for `tool.call`, `(tool_name,
args)`; for `memory.read`, `(store, query, k)`. Canonical JSON: sorted keys,
no whitespace, NFC strings, floats via repr-shortest. The normalization code
lives in `trazo.core.fingerprint` and is the **shared single implementation**
for record and replay — never reimplement it.

## 4. State hashes

`state_*_hash = "sha256:" + sha256(canonical_json(framework_state))` using
the adapter's `state_serializer` (each adapter documents exactly what is
included/excluded — e.g. LangGraph channel values, excluding non-serializable
handles, which are listed in the event as `unhashed_keys`). These hashes are
the ground truth for replay fidelity: replayed step N must reproduce
`state_after_hash` of recorded step N.

## 5. OTel mapping (ADR-005)

Every kind maps to an OTel span with `trazo.*` attributes; `llm.call` maps
onto GenAI semconv (`gen_ai.system`, `gen_ai.request.model`,
`gen_ai.usage.*`). An exporter (`trazo.core.otel_export`, post-MVP) walks
events → spans. The rule that keeps us honest: **no event field may be
semantically equivalent to an existing GenAI semconv attribute under a
different name** — reuse their vocabulary, extend only where they have none
(replay fingerprints, state hashes, policy decisions, detections).

## 6. Example minimal run (elided payloads)

```
seq 0  run.started    {framework: langgraph}
seq 1  step.started   {name: "plan", state_before_hash: h0}
seq 2  llm.call       {model: gpt-4o-mini, fingerprint: f1}
seq 3  step.finished  {state_after_hash: h1}
seq 4  step.started   {name: "search", state_before_hash: h1}
seq 5  tool.call      {tool_name: web_search, fingerprint: f2, side_effect_class: external}
seq 6  memory.write   {store: vector}
seq 7  step.finished  {state_after_hash: h2}
seq 8  run.finished   {status: ok, totals: {...}}
```
