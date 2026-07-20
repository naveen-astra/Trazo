"""Ingest API: POST /v1/ingest/events, POST /v1/ingest/blobs (API_SPEC.md).

Batch-first, partial-accept: a batch that's part-valid still gets a 202
with per-index rejection reasons — the SDK re-ships rejects to its own
spool rather than the API retrying anything (API_SPEC.md "Ingest").
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, ValidationError

from trazo_server.api.deps import get_blob_store, get_event_bus, require_api_key
from trazo_server.api.problem_details import ProblemDetailsError
from trazo_server.bus.protocol import EventBus
from trazo_server.events import EventAdapter
from trazo_server.metrics import INGEST_BLOBS_TOTAL, INGEST_EVENTS_TOTAL
from trazo_server.store.blob_store import BlobStore
from trazo_server.topics import EVENTS_STREAM

router = APIRouter(prefix="/v1", dependencies=[Depends(require_api_key)])

_MAX_BATCH = 500
_MAX_BODY_BYTES = 5 * 1024 * 1024
_SHA256_PREFIX = "sha256:"


class RejectedEvent(BaseModel):
    index: int
    reason: str


class IngestEventsRequest(BaseModel):
    events: list[dict[str, Any]]


class IngestEventsResponse(BaseModel):
    accepted: int
    rejected: list[RejectedEvent]


@router.post("/ingest/events", status_code=202, response_model=IngestEventsResponse)
async def ingest_events(
    body: IngestEventsRequest,
    request: Request,
    bus: Annotated[EventBus, Depends(get_event_bus)],
) -> IngestEventsResponse:
    content_length = request.headers.get("content-length")
    if content_length is not None and int(content_length) > _MAX_BODY_BYTES:
        raise ProblemDetailsError(
            status=413,
            title="Payload Too Large",
            detail=f"request body exceeds the {_MAX_BODY_BYTES}-byte limit",
        )
    if len(body.events) > _MAX_BATCH:
        raise ProblemDetailsError(
            status=413,
            title="Batch Too Large",
            detail=f"batch of {len(body.events)} exceeds the {_MAX_BATCH}-event limit",
        )

    accepted = 0
    rejected: list[RejectedEvent] = []
    for index, raw_event in enumerate(body.events):
        try:
            event = EventAdapter.validate_python(raw_event)
        except ValidationError as exc:
            rejected.append(RejectedEvent(index=index, reason=_first_error(exc)))
            INGEST_EVENTS_TOTAL.labels(result="rejected").inc()
            continue
        encoded = EventAdapter.dump_json(event, by_alias=True, exclude_none=True)
        await bus.publish(EVENTS_STREAM, {"event": encoded.decode("utf-8")})
        accepted += 1
        INGEST_EVENTS_TOTAL.labels(result="accepted").inc()

    return IngestEventsResponse(accepted=accepted, rejected=rejected)


def _first_error(exc: ValidationError) -> str:
    first = exc.errors()[0]
    loc = ".".join(str(part) for part in first["loc"])
    return f"{loc}: {first['msg']}" if loc else str(first["msg"])


@router.post("/ingest/blobs", status_code=201)
async def ingest_blob(
    request: Request,
    blob_store: Annotated[BlobStore, Depends(get_blob_store)],
    x_trazo_sha256: Annotated[str, Header()],
    content_type: Annotated[str, Header()] = "application/json",
) -> dict[str, str]:
    data = await request.body()
    if len(data) > _MAX_BODY_BYTES:
        raise ProblemDetailsError(
            status=413,
            title="Payload Too Large",
            detail=f"blob exceeds the {_MAX_BODY_BYTES}-byte limit",
        )

    claimed = (
        x_trazo_sha256
        if x_trazo_sha256.startswith(_SHA256_PREFIX)
        else f"{_SHA256_PREFIX}{x_trazo_sha256}"
    )
    ref = await blob_store.put(data, content_type=content_type)
    if claimed != ref.sha256:
        INGEST_BLOBS_TOTAL.labels(result="checksum_mismatch").inc()
        raise ProblemDetailsError(
            status=409,
            title="Checksum Mismatch",
            detail=f"X-Trazo-Sha256 {claimed} does not match computed {ref.sha256}",
        )
    INGEST_BLOBS_TOTAL.labels(result="stored").inc()
    return {"sha256": ref.sha256}
