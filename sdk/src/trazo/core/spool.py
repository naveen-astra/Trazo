"""Disk spool for events that failed to ship (TRZ-P2-03): ``.trazo/spool/*.ndjson``.

A spool drain is attempted before every new ship (SDK.md §2); events are
dropped — with a single rate-limited warning, at the Shipper layer — only
once the spool exceeds ``TRAZO_SPOOL_MAX_MB`` (default 256).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

_DEFAULT_MAX_BYTES = 256 * 1024 * 1024


def max_bytes_from_env() -> int:
    """``TRAZO_SPOOL_MAX_MB`` (default 256) as bytes — the spool-full
    threshold callers building a production ``DiskSpool`` should pass."""
    raw = os.environ.get("TRAZO_SPOOL_MAX_MB")
    return int(float(raw) * 1024 * 1024) if raw else _DEFAULT_MAX_BYTES


class DiskSpool:
    """One spool file per failed batch; oldest-first drain, at-least-once."""

    def __init__(self, root: Path, *, max_bytes: int = _DEFAULT_MAX_BYTES) -> None:
        self._root = root
        self._max_bytes = max_bytes
        self._root.mkdir(parents=True, exist_ok=True)

    def is_full(self) -> bool:
        return self._current_size() >= self._max_bytes

    def write(self, events: list[dict[str, Any]]) -> bool:
        """Spool one failed batch. Returns False (dropped, spool full) or True."""
        if not events or self.is_full():
            return False
        path = self._root / f"{time.time_ns()}.ndjson"
        with path.open("w", encoding="utf-8") as f:
            for event in events:
                f.write(json.dumps(event, separators=(",", ":")) + "\n")
        return True

    def drain(self) -> list[tuple[Path, list[dict[str, Any]]]]:
        """All spooled batches, oldest first — does not delete them; call
        ``remove`` per-batch once it's been shipped successfully."""
        batches = []
        for path in sorted(self._root.glob("*.ndjson")):
            lines = path.read_text(encoding="utf-8").splitlines()
            events = [json.loads(line) for line in lines if line.strip()]
            batches.append((path, events))
        return batches

    def remove(self, path: Path) -> None:
        path.unlink(missing_ok=True)

    def pending_batch_count(self) -> int:
        return sum(1 for _ in self._root.glob("*.ndjson"))

    def _current_size(self) -> int:
        return sum(p.stat().st_size for p in self._root.glob("*.ndjson"))
