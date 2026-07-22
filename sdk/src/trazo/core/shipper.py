"""Background shipper thread (TRZ-P2-03): batches events, POSTs to the
ingest API, spools on failure (SDK.md §2).

Flush triggers, whichever first: 200 events, 1 MB, or 500 ms. A spool
drain is attempted before every new ship. This class embodies both the
"EventBuffer" and "Shipper" boxes from SDK.md §2's diagram — the batching
buffer has no independent behavior worth a separate class, so it lives
here as the queue-draining loop.

Never blocks the host agent thread beyond a bounded ``queue.Queue.put``;
all I/O (HTTP, disk) happens on the background daemon thread.
"""

from __future__ import annotations

import atexit
import json
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

from trazo.core.spool import DiskSpool

log = structlog.get_logger(__name__)

FLUSH_MAX_EVENTS = 200
FLUSH_MAX_BYTES = 1_000_000
FLUSH_INTERVAL_SECONDS = 0.5
_POST_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class _StopSignal:
    pass


_STOP = _StopSignal()


class Shipper:
    """Owns the background thread; adapters/Recorder only call ``enqueue``."""

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        spool: DiskSpool,
        client: httpx.Client | None = None,
        autostart: bool = True,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._api_key = api_key
        self._spool = spool
        self._client = client or httpx.Client(timeout=_POST_TIMEOUT_SECONDS)
        self._queue: queue.Queue[dict[str, Any] | _StopSignal] = queue.Queue()
        self._thread = threading.Thread(
            target=self._run, name="trazo-shipper", daemon=True
        )
        self._stopped = False
        if autostart:
            self.start()

    def start(self) -> None:
        self._thread.start()
        atexit.register(self.flush_and_stop)

    def enqueue(self, event: dict[str, Any]) -> None:
        if self._stopped:
            log.warning("shipper.enqueue_after_stop", kind=event.get("kind"))
            return
        self._queue.put(event)

    def flush_and_stop(self, *, timeout: float = 5.0) -> None:
        if self._stopped:
            return
        self._stopped = True
        self._queue.put(_STOP)
        self._thread.join(timeout=timeout)

    def _run(self) -> None:
        buffer: list[dict[str, Any]] = []
        buffer_bytes = 0
        window_start = time.monotonic()

        while True:
            remaining = FLUSH_INTERVAL_SECONDS - (time.monotonic() - window_start)
            stop = False
            try:
                item = self._queue.get(timeout=max(remaining, 0.001))
                if isinstance(item, _StopSignal):
                    stop = True
                else:
                    buffer.append(item)
                    buffer_bytes += len(json.dumps(item, separators=(",", ":")))
            except queue.Empty:
                pass

            time_expired = (time.monotonic() - window_start) >= FLUSH_INTERVAL_SECONDS
            if (
                stop
                or len(buffer) >= FLUSH_MAX_EVENTS
                or buffer_bytes >= FLUSH_MAX_BYTES
                or time_expired
            ):
                if buffer:
                    self._flush(buffer)
                    buffer = []
                    buffer_bytes = 0
                window_start = time.monotonic()

            if stop:
                return

    def _flush(self, events: list[dict[str, Any]]) -> None:
        self._drain_spool()
        if not self._post(events) and not self._spool.write(events):
            log.warning("shipper.dropped_events_spool_full", count=len(events))

    def _drain_spool(self) -> None:
        for path, spooled_events in self._spool.drain():
            if self._post(spooled_events):
                self._spool.remove(path)
            else:
                break  # still failing; retry the whole spool next cycle

    def _post(self, events: list[dict[str, Any]]) -> bool:
        try:
            response = self._client.post(
                f"{self._endpoint}/v1/ingest/events",
                json={"events": events},
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
            response.raise_for_status()
            return True
        except httpx.HTTPError as exc:
            log.warning("shipper.post_failed", count=len(events), error=str(exc))
            return False
