"""SDK-side replay bundle model (TRZ-P4-01): parses the NDJSON the
control plane's ``GET /v1/runs/{id}/replay-bundle`` returns
(REPLAY_ENGINE.md §7) into a structure the Substituter (TRZ-P4-02) and
Step API (TRZ-P4-05) build on.

Deliberately dumb: this module only parses and indexes. It never fetches
over the network — that's ``bundle_loader.py``'s job — so it has no
``httpx`` dependency and is trivial to construct in tests from a raw
NDJSON string.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


class InvalidBundleError(Exception):
    """Raised when NDJSON doesn't parse into a valid bundle — a missing
    manifest line, or an unrecognized schema tag. Never silently treated
    as an empty bundle."""


@dataclass(frozen=True)
class RecordedEvent:
    """One event line of a replay bundle — the same shape the query API's
    ``EventOut`` returns."""

    run_id: str
    seq: int
    event_id: str
    kind: str
    ts: str
    step_id: str | None
    agent_id: str | None
    fingerprint: str | None
    payload: dict[str, Any]
    blobs: list[dict[str, Any]]
    # 0 for an event the SDK recorded; 1, 2, ... for an event the control
    # plane recorded right after the one at `seq` (a detection, a policy
    # decision). Absent from bundles served before it existed.
    sub_seq: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RecordedEvent:
        return cls(
            run_id=data["run_id"],
            seq=data["seq"],
            event_id=data["event_id"],
            kind=data["kind"],
            ts=data["ts"],
            step_id=data.get("step_id"),
            agent_id=data.get("agent_id"),
            fingerprint=data.get("fingerprint"),
            payload=data["payload"],
            blobs=data.get("blobs", []),
            sub_seq=data.get("sub_seq", 0),
        )


@dataclass(frozen=True)
class ReplayBundle:
    """A parsed, immutable replay bundle: manifest fields plus every
    event, in seq order and pre-indexed by kind for the Substituter's
    per-kind cursors (REPLAY_ENGINE.md §2)."""

    run_id: str
    project_id: str
    framework: str
    status: str
    started_at: str
    finished_at: str | None
    tags: dict[str, Any]
    totals: dict[str, Any]
    event_count: int
    blob_manifest: list[dict[str, Any]]
    events: list[RecordedEvent]
    _events_by_kind: dict[str, list[RecordedEvent]] = field(
        default_factory=dict, compare=False, repr=False
    )

    def events_by_kind(self, kind: str) -> list[RecordedEvent]:
        """Every recorded event of ``kind``, in seq order."""
        return self._events_by_kind.get(kind, [])

    @classmethod
    def parse_ndjson(cls, data: bytes) -> ReplayBundle:
        lines = [line for line in data.decode("utf-8").split("\n") if line.strip()]
        if not lines:
            raise InvalidBundleError("empty bundle: no manifest line")

        manifest = json.loads(lines[0])
        if manifest.get("schema") != "trazo.replay-bundle.v1":
            raise InvalidBundleError(
                f"unrecognized bundle schema: {manifest.get('schema')!r}"
            )

        events = [RecordedEvent.from_dict(json.loads(line)) for line in lines[1:]]
        if len(events) != manifest["event_count"]:
            raise InvalidBundleError(
                f"manifest declares {manifest['event_count']} events, "
                f"found {len(events)}"
            )

        by_kind: dict[str, list[RecordedEvent]] = defaultdict(list)
        for event in events:
            by_kind[event.kind].append(event)

        return cls(
            run_id=manifest["run_id"],
            project_id=manifest["project_id"],
            framework=manifest["framework"],
            status=manifest["status"],
            started_at=manifest["started_at"],
            finished_at=manifest.get("finished_at"),
            tags=manifest["tags"],
            totals=manifest["totals"],
            event_count=manifest["event_count"],
            blob_manifest=manifest["blob_manifest"],
            events=events,
            _events_by_kind=dict(by_kind),
        )
