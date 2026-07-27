"""Unit tests for trazo.core.shipper.Shipper (TRZ-P2-03).

``test_shipper__kill_9_spool_drain_recovers_all_events`` is the task's
named DoD: a batch spooled by a "process" that never got to ship it (as
if killed before the next flush) must be fully recovered — posted and
removed from disk — by a fresh Shipper once the endpoint is reachable
again, with no event lost.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import httpx

from trazo.core.shipper import (
    _POST_TIMEOUT_SECONDS,
    RECOMMENDED_SHUTDOWN_TIMEOUT_SECONDS,
    Shipper,
)
from trazo.core.spool import DiskSpool


class _RecordingTransport(httpx.MockTransport):
    """Wraps MockTransport to also record every request body it saw."""

    def __init__(self, status_code: int = 202) -> None:
        self.requests: list[dict[str, object]] = []
        self._status_code = status_code
        self._lock = threading.Lock()
        super().__init__(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        with self._lock:
            self.requests.append(body)
        return httpx.Response(self._status_code, json={"accepted": len(body["events"])})


def _client(transport: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=transport)


def test_shipper__ships_enqueued_events_on_flush(tmp_path: Path) -> None:
    transport = _RecordingTransport()
    shipper = Shipper(
        endpoint="http://example.test",
        api_key="k",
        spool=DiskSpool(tmp_path),
        client=_client(transport),
    )

    shipper.enqueue({"seq": 0, "kind": "run.started"})
    shipper.flush_and_stop()

    assert len(transport.requests) == 1
    assert transport.requests[0]["events"] == [{"seq": 0, "kind": "run.started"}]
    assert DiskSpool(tmp_path).pending_batch_count() == 0


def test_shipper__spools_events_on_post_failure(tmp_path: Path) -> None:
    transport = _RecordingTransport(status_code=500)
    spool = DiskSpool(tmp_path)
    shipper = Shipper(
        endpoint="http://example.test",
        api_key="k",
        spool=spool,
        client=_client(transport),
    )

    shipper.enqueue({"seq": 0, "kind": "run.started"})
    shipper.flush_and_stop()

    assert spool.pending_batch_count() == 1
    [(_path, events)] = spool.drain()
    assert events == [{"seq": 0, "kind": "run.started"}]


def test_shipper__auth_header_carries_the_api_key(tmp_path: Path) -> None:
    seen_headers: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.append(request.headers.get("authorization", ""))
        return httpx.Response(202, json={"accepted": 1})

    shipper = Shipper(
        endpoint="http://example.test",
        api_key="secret-key",
        spool=DiskSpool(tmp_path),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    shipper.enqueue({"seq": 0})
    shipper.flush_and_stop()

    assert seen_headers == ["Bearer secret-key"]


def test_shipper__kill_9_spool_drain_recovers_all_events(tmp_path: Path) -> None:
    """Simulates a process that spooled a batch (e.g. the endpoint was
    down) and then died before it could retry — a fresh Shipper pointed
    at the same spool directory, once the endpoint is reachable again,
    must recover and ship every spooled event, with nothing lost."""
    spool_root = tmp_path / "spool"
    crashed_process_spool = DiskSpool(spool_root)
    stale_batch = [
        {"seq": 0, "kind": "run.started"},
        {"seq": 1, "kind": "step.started"},
    ]
    assert crashed_process_spool.write(stale_batch) is True
    assert crashed_process_spool.pending_batch_count() == 1

    # "process restarts": a brand-new Shipper, same spool directory, and
    # this time the endpoint is reachable.
    transport = _RecordingTransport()
    fresh_spool = DiskSpool(spool_root)
    shipper = Shipper(
        endpoint="http://example.test",
        api_key="k",
        spool=fresh_spool,
        client=_client(transport),
    )

    # any new activity triggers a flush cycle, which drains the spool first.
    shipper.enqueue({"seq": 2, "kind": "step.finished"})
    shipper.flush_and_stop()

    assert fresh_spool.pending_batch_count() == 0
    all_shipped_events = [e for req in transport.requests for e in req["events"]]
    assert all_shipped_events == [
        {"seq": 0, "kind": "run.started"},
        {"seq": 1, "kind": "step.started"},
        {"seq": 2, "kind": "step.finished"},
    ]


def test_shipper__spool_full_drops_with_warning_not_a_crash(tmp_path: Path) -> None:
    transport = _RecordingTransport(status_code=500)
    spool = DiskSpool(
        tmp_path, max_bytes=1
    )  # effectively always full after first write
    shipper = Shipper(
        endpoint="http://example.test",
        api_key="k",
        spool=spool,
        client=_client(transport),
    )

    shipper.enqueue({"seq": 0})
    shipper.flush_and_stop()
    assert spool.pending_batch_count() == 1  # first write always allowed

    # second batch: spool is now full, post still fails -> dropped, not spooled
    shipper2 = Shipper(
        endpoint="http://example.test",
        api_key="k",
        spool=spool,
        client=_client(transport),
    )
    shipper2.enqueue({"seq": 1})
    shipper2.flush_and_stop()

    assert spool.pending_batch_count() == 1  # unchanged: the second batch was dropped


def test_recommended_shutdown_timeout__covers_two_full_post_attempts() -> None:
    """TRZ-P3-03: one flush cycle can need two full POST attempts against
    an unreachable endpoint (_drain_spool()'s retry, then the new batch's
    own _post()) — a shutdown()/flush_and_stop() timeout shorter than that
    can return via join()'s own timeout while the daemon thread is still
    mid-POST, and the process exiting anyway then kills it, silently
    dropping whatever it was sending. Locks in the invariant that made
    this the new default, not just the specific numbers."""
    assert RECOMMENDED_SHUTDOWN_TIMEOUT_SECONDS >= 2 * _POST_TIMEOUT_SECONDS
