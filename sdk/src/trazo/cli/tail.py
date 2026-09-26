"""``trazo tail <run_id>`` — stream one run's events live (SDK.md §5).

A thin SSE client over ``GET /v1/live/runs/{run_id}`` (TRZ-P2-06). That
endpoint is unauthenticated (query/live bind to localhost by default,
ADR-009), so this sends no credentials. The stream closes on its own once
the server observes ``run.finished`` (api/live.py); otherwise it runs until
the process is interrupted.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable, Iterator
from typing import Any, TextIO

import httpx


def _parse_sse(lines: Iterable[str]) -> Iterator[dict[str, Any]]:
    """Reassemble ``data:`` fields from an SSE line stream into events.

    ``id:`` lines are ignored — this is a live, one-shot tail, not a
    resumable client, so there is nothing to echo back as ``Last-Event-ID``.
    """
    data_lines: list[str] = []
    for line in lines:
        if line == "":
            if data_lines:
                yield json.loads("\n".join(data_lines))
                data_lines = []
            continue
        if line.startswith("data:"):
            data_lines.append(line[len("data:") :].lstrip(" "))
    if data_lines:
        yield json.loads("\n".join(data_lines))


def _format_event(event: dict[str, Any]) -> str:
    step = event.get("step_id") or "-"
    agent = event.get("agent_id") or "-"
    seq, ts, kind = event["seq"], event["ts"], event["kind"]
    return f"{seq:>5}  {ts}  step={step:<20} agent={agent:<12} {kind}"


def tail_run(
    run_id: str,
    *,
    endpoint: str,
    api_key: str | None = None,
    out: TextIO = sys.stdout,
    client: httpx.Client | None = None,
) -> int:
    """Stream ``run_id``'s events to ``out`` until the run finishes.

    ``client`` is injectable (a real ``httpx.Client`` is built by default)
    so tests can pass one wired to an ``httpx.MockTransport``.

    Returns a process exit code: 0 on a clean end-of-stream, 1 on an HTTP
    or connection error.
    """
    url = f"{endpoint}/v1/live/runs/{run_id}"
    owns_client = client is None
    client = client or httpx.Client(timeout=None)
    try:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        with client.stream("GET", url, headers=headers) as response:
            if response.status_code != 200:
                print(
                    f"trazo tail: HTTP {response.status_code} from {url}",
                    file=sys.stderr,
                )
                return 1
            for event in _parse_sse(response.iter_lines()):
                print(_format_event(event), file=out, flush=True)
    except httpx.HTTPError as exc:
        print(f"trazo tail: could not reach {endpoint}: {exc}", file=sys.stderr)
        return 1
    finally:
        if owns_client:
            client.close()
    return 0
