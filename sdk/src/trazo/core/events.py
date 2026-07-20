"""Pydantic v2 models for the Trazo trace-event envelope.

Mirrors ``schema/trace-event.v1.schema.json`` (and EVENTS.md) field for
field. This is the SDK half of the pattern; the control-plane half lives
at ``trazo_server.events`` in the control-plane/ package — the two must
never cross-import (DEVELOPMENT_GUIDE.md §3), so the model definitions are
deliberately duplicated, not shared. ``tests/test_events_contract.py``
asserts this module stays equivalent to the JSON Schema; if you change one
without the other, that test fails.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter

EventId = Annotated[str, StringConstraints(pattern=r"^evt_")]
RunId = Annotated[str, StringConstraints(pattern=r"^run_")]
StepId = Annotated[str, StringConstraints(pattern=r"^stp_")]
Sha256Ref = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]

Framework = Literal["langgraph", "crewai", "custom"]
RunStatus = Literal["ok", "error", "blocked", "cancelled"]
SideEffectClass = Literal["read", "write", "external"]
MemoryStore = Literal["vector", "kv", "framework"]
MessageType = Literal["handoff", "delegation", "result", "other"]
PolicyDecisionValue = Literal["allow", "deny", "escalate"]
PolicyMode = Literal["observe", "enforce"]
DetectorName = Literal["loop", "budget", "thrash", "drift"]
Severity = Literal["info", "warn", "critical"]
DiagnosticLevel = Literal["debug", "info", "warn", "error"]

EventKind = Literal[
    "run.started",
    "run.finished",
    "step.started",
    "step.finished",
    "llm.call",
    "tool.call",
    "memory.read",
    "memory.write",
    "agent.message",
    "plan.updated",
    "human.checkpoint",
    "policy.decision",
    "detection.raised",
    "sdk.diagnostic",
]


class _Model(BaseModel):
    """Base for every wire model: rejects unknown fields, per the JSON schema."""

    model_config = ConfigDict(extra="forbid")


class OTelRef(_Model):
    """OTel bridge (EVENTS.md §1) — optional trace/span id pair."""

    trace_id: str | None = None
    span_id: str | None = None


class BlobEntry(_Model):
    """One entry in the envelope's ``blobs`` offload manifest."""

    field: str = Field(min_length=1)
    sha256: Sha256Ref
    bytes: int = Field(ge=0)


class ErrorInfo(_Model):
    """Shared error shape used by run.finished, llm.call, and tool.call payloads."""

    type: str
    message: str
    stack: str | None = None


# ---- payloads (EVENTS.md §2) ----


class RunStartedPayload(_Model):
    framework: Framework
    framework_version: str
    sdk_version: str
    entry_input: Any
    tags: dict[str, Any]
    code_ref: str | None = None


class RunTotals(_Model):
    events: int = Field(ge=0)
    llm_calls: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    cost_usd: float = Field(ge=0)
    tokens_in: int = Field(ge=0)
    tokens_out: int = Field(ge=0)
    duration_ms: float = Field(ge=0)


class RunFinishedPayload(_Model):
    status: RunStatus
    totals: RunTotals
    error: ErrorInfo | None = None


class StepStartedPayload(_Model):
    name: str
    step_index: int = Field(ge=0)
    state_before_hash: Sha256Ref
    state_before: Any
    unhashed_keys: list[str] | None = None


class StepFinishedPayload(_Model):
    status: str
    state_after_hash: Sha256Ref
    state_after: Any
    duration_ms: float = Field(ge=0)
    unhashed_keys: list[str] | None = None


class LlmCallPayload(_Model):
    provider: str
    model: str
    params: dict[str, Any]
    messages_in: Any
    response: Any
    tokens_in: int = Field(ge=0)
    tokens_out: int = Field(ge=0)
    cost_usd: float = Field(ge=0)
    latency_ms: float = Field(ge=0)
    error: ErrorInfo | None = None


class ToolCallPayload(_Model):
    tool_name: str
    args: Any
    result: Any
    status: str
    latency_ms: float = Field(ge=0)
    side_effect_class: SideEffectClass
    error: ErrorInfo | None = None


class MemoryReadPayload(_Model):
    store: MemoryStore
    query: Any
    results: Any
    k: int = Field(ge=0)
    latency_ms: float = Field(ge=0)


class MemoryWritePayload(_Model):
    store: MemoryStore
    key_or_ns: str
    value: Any
    latency_ms: float = Field(ge=0)


class AgentMessagePayload(_Model):
    from_agent: str
    to_agent: str
    content: Any
    message_type: MessageType


class PlanUpdatedPayload(_Model):
    plan: Any
    reason: str


class HumanCheckpointPayload(_Model):
    prompt: str
    response: Any
    latency_ms: float = Field(ge=0)


class PolicyActionRef(_Model):
    fingerprint: Sha256Ref
    kind: EventKind


class PolicyDecisionPayload(_Model):
    policy_id: str
    action_ref: PolicyActionRef
    decision: PolicyDecisionValue
    reasons: list[str]
    eval_latency_ms: float = Field(ge=0)
    mode: PolicyMode


class DetectionRaisedPayload(_Model):
    detector: DetectorName
    severity: Severity
    evidence_event_ids: list[EventId]
    details: dict[str, Any]
    window: dict[str, Any]


class SdkDiagnosticPayload(_Model):
    level: DiagnosticLevel
    message: str
    dropped_events: int | None = Field(default=None, ge=0)


PAYLOAD_MODEL_BY_KIND: dict[str, type[BaseModel]] = {
    "run.started": RunStartedPayload,
    "run.finished": RunFinishedPayload,
    "step.started": StepStartedPayload,
    "step.finished": StepFinishedPayload,
    "llm.call": LlmCallPayload,
    "tool.call": ToolCallPayload,
    "memory.read": MemoryReadPayload,
    "memory.write": MemoryWritePayload,
    "agent.message": AgentMessagePayload,
    "plan.updated": PlanUpdatedPayload,
    "human.checkpoint": HumanCheckpointPayload,
    "policy.decision": PolicyDecisionPayload,
    "detection.raised": DetectionRaisedPayload,
    "sdk.diagnostic": SdkDiagnosticPayload,
}

# Boundary kinds: fingerprint is required at the envelope level (EVENTS.md §2.3-2.4).
BOUNDARY_KINDS: frozenset[str] = frozenset(
    {"llm.call", "tool.call", "memory.read", "memory.write", "human.checkpoint"}
)


# ---- envelope (EVENTS.md §1) ----


class _EnvelopeBase(_Model):
    """Common envelope fields shared by every event kind."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_: Literal["trazo.v1"] = Field(alias="schema")
    event_id: EventId
    run_id: RunId
    project: str = Field(min_length=1)
    seq: int = Field(ge=0)
    ts: datetime
    step_id: StepId | None = None
    agent_id: str | None = None
    parent_event_id: EventId | None = None
    fingerprint: Sha256Ref | None = None
    otel: OTelRef | None = None
    blobs: list[BlobEntry] = Field(default_factory=list)


class RunStartedEvent(_EnvelopeBase):
    kind: Literal["run.started"]
    payload: RunStartedPayload


class RunFinishedEvent(_EnvelopeBase):
    kind: Literal["run.finished"]
    payload: RunFinishedPayload


class StepStartedEvent(_EnvelopeBase):
    kind: Literal["step.started"]
    payload: StepStartedPayload


class StepFinishedEvent(_EnvelopeBase):
    kind: Literal["step.finished"]
    payload: StepFinishedPayload


class LlmCallEvent(_EnvelopeBase):
    kind: Literal["llm.call"]
    payload: LlmCallPayload
    fingerprint: Sha256Ref


class ToolCallEvent(_EnvelopeBase):
    kind: Literal["tool.call"]
    payload: ToolCallPayload
    fingerprint: Sha256Ref


class MemoryReadEvent(_EnvelopeBase):
    kind: Literal["memory.read"]
    payload: MemoryReadPayload
    fingerprint: Sha256Ref


class MemoryWriteEvent(_EnvelopeBase):
    kind: Literal["memory.write"]
    payload: MemoryWritePayload
    fingerprint: Sha256Ref


class AgentMessageEvent(_EnvelopeBase):
    kind: Literal["agent.message"]
    payload: AgentMessagePayload


class PlanUpdatedEvent(_EnvelopeBase):
    kind: Literal["plan.updated"]
    payload: PlanUpdatedPayload


class HumanCheckpointEvent(_EnvelopeBase):
    kind: Literal["human.checkpoint"]
    payload: HumanCheckpointPayload
    fingerprint: Sha256Ref


class PolicyDecisionEvent(_EnvelopeBase):
    kind: Literal["policy.decision"]
    payload: PolicyDecisionPayload


class DetectionRaisedEvent(_EnvelopeBase):
    kind: Literal["detection.raised"]
    payload: DetectionRaisedPayload


class SdkDiagnosticEvent(_EnvelopeBase):
    kind: Literal["sdk.diagnostic"]
    payload: SdkDiagnosticPayload


Event = Annotated[
    RunStartedEvent
    | RunFinishedEvent
    | StepStartedEvent
    | StepFinishedEvent
    | LlmCallEvent
    | ToolCallEvent
    | MemoryReadEvent
    | MemoryWriteEvent
    | AgentMessageEvent
    | PlanUpdatedEvent
    | HumanCheckpointEvent
    | PolicyDecisionEvent
    | DetectionRaisedEvent
    | SdkDiagnosticEvent,
    Field(discriminator="kind"),
]

EVENT_MODEL_BY_KIND: dict[str, type[_EnvelopeBase]] = {
    "run.started": RunStartedEvent,
    "run.finished": RunFinishedEvent,
    "step.started": StepStartedEvent,
    "step.finished": StepFinishedEvent,
    "llm.call": LlmCallEvent,
    "tool.call": ToolCallEvent,
    "memory.read": MemoryReadEvent,
    "memory.write": MemoryWriteEvent,
    "agent.message": AgentMessageEvent,
    "plan.updated": PlanUpdatedEvent,
    "human.checkpoint": HumanCheckpointEvent,
    "policy.decision": PolicyDecisionEvent,
    "detection.raised": DetectionRaisedEvent,
    "sdk.diagnostic": SdkDiagnosticEvent,
}

EventAdapter: TypeAdapter[Event] = TypeAdapter(Event)
