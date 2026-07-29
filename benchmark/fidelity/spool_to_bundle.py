#!/usr/bin/env python3
"""Build a replay-bundle cache file directly from a Shipper's disk spool
(TRZ-P4-08), skipping the control plane entirely.

    python benchmark/fidelity/spool_to_bundle.py <run_id> \\
        --spool-dir .trazo/spool --cache-dir .trazo/cache

Every real integration test in this project that needs to replay a run
without a live control plane (no Docker in the environment this was
built in — same constraint as the nightly corpus job) goes through this:
run a demo for real against an unreachable endpoint (it spools instead of
failing, per Shipper's documented fallback), then convert the spool
straight into the same NDJSON shape ``GET /v1/runs/{id}/replay-bundle``
would have served, byte-for-byte compatible with
``trazo.core.replay_bundle.ReplayBundle.parse_ndjson``.

Deliberately stdlib-only, matching ``benchmark/corpus/archive_run.py``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


class NoRunStartedError(Exception):
    """Raised when the spool has no run.started event for ``run_id`` —
    either the wrong run_id was given, or the spool was drained/rotated
    before this ran."""


def _load_spooled_events(spool_dir: Path, run_id: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for path in sorted(spool_dir.glob("*.ndjson")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get("run_id") == run_id:
                events.append(event)
    events.sort(key=lambda e: e["seq"])
    return events


def _event_out(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": event["run_id"],
        "seq": event["seq"],
        "event_id": event["event_id"],
        "kind": event["kind"],
        "ts": event["ts"],
        "step_id": event.get("step_id"),
        "agent_id": event.get("agent_id"),
        "fingerprint": event.get("fingerprint"),
        "payload": event["payload"],
        "blobs": [],
    }


def build_bundle_ndjson(events: list[dict[str, Any]], *, run_id: str) -> bytes:
    """The exact NDJSON bytes ``ReplayBundle.parse_ndjson`` expects:
    manifest line, then one line per event in seq order."""
    run_started = next((e for e in events if e["kind"] == "run.started"), None)
    if run_started is None:
        raise NoRunStartedError(f"no run.started event found for {run_id!r} in spool")
    run_finished = next((e for e in events if e["kind"] == "run.finished"), None)

    manifest = {
        "schema": "trazo.replay-bundle.v1",
        "run_id": run_id,
        "project_id": run_started["project"],
        "framework": run_started["payload"]["framework"],
        "status": "ok" if run_finished else "running",
        "started_at": run_started["ts"],
        "finished_at": run_finished["ts"] if run_finished else None,
        "tags": run_started["payload"].get("tags", {}),
        "totals": run_finished["payload"].get("totals", {}) if run_finished else {},
        "event_count": len(events),
        "blob_manifest": [],
    }

    lines = [json.dumps(manifest)] + [json.dumps(_event_out(e)) for e in events]
    return ("\n".join(lines) + "\n").encode("utf-8")


def write_bundle_cache(*, spool_dir: Path, cache_dir: Path, run_id: str) -> Path:
    events = _load_spooled_events(spool_dir, run_id)
    data = build_bundle_ndjson(events, run_id=run_id)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{run_id}.ndjson"
    cache_path.write_bytes(data)
    return cache_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    parser.add_argument("--spool-dir", type=Path, default=Path(".trazo/spool"))
    parser.add_argument("--cache-dir", type=Path, default=Path(".trazo/cache"))
    args = parser.parse_args()

    try:
        cache_path = write_bundle_cache(
            spool_dir=args.spool_dir, cache_dir=args.cache_dir, run_id=args.run_id
        )
    except NoRunStartedError as exc:
        print(f"spool_to_bundle: {exc}", file=sys.stderr)
        return 1

    print(f"wrote {cache_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
