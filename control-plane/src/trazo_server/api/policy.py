"""Policy API: `POST /v1/policy/evaluate` (API_SPEC.md "Policy", ADR-006).

Synchronous, latency-budgeted delegate to the OPA sidecar: evaluate the
governed action, record the decision as a `policy.decision` event
*before* responding (this is what makes it a real inline-governance
event, not eventually-consistent reporting), and hand the SDK back
exactly what it needs to decide whether to proceed.

On an OPA failure (timeout, unreachable, bad response) this endpoint
raises a 503 and records nothing — there is no decision to record. The
SDK's own `TRAZO_POLICY_FAIL` (ADR-006) decides fail-open/closed from
that failure; the control plane has no opinion on it.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from trazo_server.api.deps import (
    get_event_bus,
    get_opa_client,
    get_trace_store,
    require_api_key,
)
from trazo_server.api.problem_details import ProblemDetailsError
from trazo_server.bus.protocol import EventBus
from trazo_server.errors import OpaUnavailableError
from trazo_server.events import Event, EventAdapter, EventKind, PolicyMode, Sha256Ref
from trazo_server.metrics import POLICY_EVAL_LATENCY_SECONDS
from trazo_server.policy.opa_client import OpaClient
from trazo_server.store.trace_store import TraceStore
from trazo_server.topics import EVENTS_STREAM
from trazo_server.ulid import new_event_id

router = APIRouter(prefix="/v1", dependencies=[Depends(require_api_key)])


class PolicyActionIn(BaseModel):
    kind: EventKind
    fingerprint: Sha256Ref
    tool_name: str | None = None
    args_summary: dict[str, Any] = Field(default_factory=dict)
    side_effect_class: str | None = None
    projected_cost_usd: float = 0.0


class PolicyRunContextIn(BaseModel):
    cost_usd_so_far: float = 0.0
    active_detections: list[str] = Field(default_factory=list)


class PolicyEvaluateRequest(BaseModel):
    run_id: str
    project: str
    mode: PolicyMode
    action: PolicyActionIn
    run_context: PolicyRunContextIn


class PolicyEvaluateResponse(BaseModel):
    decision: str
    policy_id: str
    reasons: list[str]
    eval_ms: float


@router.post("/policy/evaluate", response_model=PolicyEvaluateResponse)
async def evaluate_policy(
    body: PolicyEvaluateRequest,
    opa: Annotated[OpaClient, Depends(get_opa_client)],
    trace_store: Annotated[TraceStore, Depends(get_trace_store)],
    bus: Annotated[EventBus, Depends(get_event_bus)],
) -> PolicyEvaluateResponse:
    input_doc = {
        "run_id": body.run_id,
        "action": body.action.model_dump(mode="json"),
        "run_context": body.run_context.model_dump(mode="json"),
    }

    start = time.perf_counter()
    try:
        result = await opa.evaluate(input_doc)
    except OpaUnavailableError as exc:
        raise ProblemDetailsError(
            status=503, title="Policy Unavailable", detail=str(exc)
        ) from exc
    eval_seconds = time.perf_counter() - start
    POLICY_EVAL_LATENCY_SECONDS.observe(eval_seconds)
    eval_ms = eval_seconds * 1000

    decision = str(result.get("decision", "allow"))
    policy_id = str(result.get("policy_id", ""))
    reasons = [str(r) for r in result.get("reasons", [])]

    event_id = new_event_id()
    ts = datetime.now(timezone.utc)
    payload = {
        "policy_id": policy_id,
        "action_ref": {
            "fingerprint": body.action.fingerprint,
            "kind": body.action.kind,
        },
        "decision": decision,
        "reasons": reasons,
        "eval_latency_ms": eval_ms,
        "mode": body.mode,
    }

    # Durable write first (this is what "before responding" means, ADR-006
    # -- the decision is recorded no matter what happens next), then
    # republished onto the bus so StoreWorker's generic consumption
    # maintains the policy_decisions projection (TRZ-P6-05) and any live
    # SSE/dashboard subscriber sees it immediately, mirroring
    # PersistDetection's identical two-step shape (TRZ-P5-06).
    seq = await trace_store.append_event(
        run_id=body.run_id,
        event_id=event_id,
        kind="policy.decision",
        ts=ts,
        fingerprint=None,
        payload=payload,
    )
    envelope: Event = EventAdapter.validate_python(
        {
            "schema": "trazo.v1",
            "event_id": event_id,
            "run_id": body.run_id,
            "project": body.project,
            "seq": seq,
            "ts": ts.isoformat(),
            "kind": "policy.decision",
            "payload": payload,
        }
    )
    encoded = EventAdapter.dump_json(envelope, by_alias=True, exclude_none=True)
    await bus.publish(EVENTS_STREAM, {"event": encoded.decode("utf-8")})

    return PolicyEvaluateResponse(
        decision=decision, policy_id=policy_id, reasons=reasons, eval_ms=eval_ms
    )
