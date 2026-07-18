# ADR-006: Policy enforcement is a synchronous SDK hook, not a pipeline consumer

- **Status:** accepted
- **Date:** 2026-07-18

## Context
"Block the action before it executes" cannot be satisfied by evaluating
policies on the async event pipeline — by the time a pipeline consumer
sees the event, the action has run. The proposal's architecture diagram
left this ambiguity unresolved; it is the difference between governance
and reporting.

## Decision
The SDK calls `POST /v1/policy/evaluate` synchronously immediately before
executing governed actions (default scope: `tool.call` with
`side_effect_class ∈ {write, external}`). Latency budget 150 ms; the
control plane delegates to an OPA sidecar and records the decision as an
event before responding. Timeout/unreachable behavior is explicit
configuration: `TRAZO_POLICY_FAIL=open` (default; log loudly, proceed) or
`closed` (deny). Modes `off|observe|enforce` allow burn-in without
blocking.

## Consequences
Real inline governance with an honest latency cost on governed actions
only. Fail-open default favors availability for an observability tool;
teams with hard compliance flip to fail-closed knowingly. Cost: the SDK
gains one synchronous network dependency — mitigated by decision caching
for identical `(policy set, action fingerprint)` within a run. Local
embedded evaluation (OPA-wasm) is the roadmap path if the hop proves too
costly in practice.
