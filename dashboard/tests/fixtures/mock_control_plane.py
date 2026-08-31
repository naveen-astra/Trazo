#!/usr/bin/env python3
"""Stdlib-only fixture control plane for running tests/timeline.spec.ts
without a live docker compose stack. Serves exactly the response shapes
control-plane's query/live APIs produce (RunOut/RunsPage/EventOut/SSE
framing), for one canned "phase2-smoke" run whose 8-event sequence matches
what the real toy LangGraph agent (sdk/tests/agents/research_assistant.py)
actually produces end-to-end (verified separately by running it against a
real Shipper and inspecting the shipped/spooled events).

scripts/smoke/phase2.sh against a real compose stack is the source-of-truth
integration check; this is a fast, dependency-free stand-in so the
dashboard's own rendering can be verified in a real browser without
Postgres/Redis/the control plane running.

Run: `python tests/fixtures/mock_control_plane.py` (from `dashboard/`),
then in another terminal `npm run dev` and `npm run test:e2e`.
"""

from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

RUN_ID = "run_01SMOKE0000000000000000000"
PROJECT = "phase2-smoke"

EVENTS = [
    {
        "run_id": RUN_ID, "seq": 0, "event_id": "evt_00", "kind": "run.started",
        "ts": "2026-07-24T12:00:00Z", "step_id": None, "agent_id": None,
        "fingerprint": None, "blobs": [],
        "payload": {
            "framework": "langgraph", "framework_version": "0.2.0",
            "sdk_version": "0.1.0",
            "entry_input": {"messages": [{"content": "find me something", "type": "human"}], "search_result": ""},
            "tags": {},
        },
    },
    {
        "run_id": RUN_ID, "seq": 1, "event_id": "evt_01", "kind": "step.started",
        "ts": "2026-07-24T12:00:00Z", "step_id": "step_plan", "agent_id": "plan",
        "fingerprint": None, "blobs": [],
        "payload": {"name": "plan", "state_before_hash": "sha256:" + "a" * 64},
    },
    {
        "run_id": RUN_ID, "seq": 2, "event_id": "evt_02", "kind": "llm.call",
        "ts": "2026-07-24T12:00:00Z", "step_id": "step_plan", "agent_id": "plan",
        "fingerprint": "sha256:" + "b" * 64, "blobs": [],
        "payload": {
            "model": "fake-model-v1", "tokens_in": 5, "tokens_out": 3,
            "response": {"content": "I will search for that.", "type": "ai"},
        },
    },
    {
        "run_id": RUN_ID, "seq": 3, "event_id": "evt_03", "kind": "step.finished",
        "ts": "2026-07-24T12:00:00Z", "step_id": "step_plan", "agent_id": "plan",
        "fingerprint": None, "blobs": [],
        "payload": {"name": "plan", "state_after_hash": "sha256:" + "c" * 64, "status": "ok"},
    },
    {
        "run_id": RUN_ID, "seq": 4, "event_id": "evt_04", "kind": "step.started",
        "ts": "2026-07-24T12:00:01Z", "step_id": "step_search", "agent_id": "search",
        "fingerprint": None, "blobs": [],
        "payload": {"name": "search", "state_before_hash": "sha256:" + "d" * 64},
    },
    {
        "run_id": RUN_ID, "seq": 5, "event_id": "evt_05", "kind": "tool.call",
        "ts": "2026-07-24T12:00:01Z", "step_id": "step_search", "agent_id": "search",
        "fingerprint": "sha256:" + "e" * 64, "blobs": [],
        "payload": {
            "tool_name": "web_search", "args": {"query": "trazo"},
            "side_effect_class": "read", "status": "ok", "result": "results for trazo",
        },
    },
    {
        "run_id": RUN_ID, "seq": 6, "event_id": "evt_06", "kind": "step.finished",
        "ts": "2026-07-24T12:00:01Z", "step_id": "step_search", "agent_id": "search",
        "fingerprint": None, "blobs": [],
        "payload": {"name": "search", "state_after_hash": "sha256:" + "f" * 64, "status": "ok"},
    },
    {
        "run_id": RUN_ID, "seq": 7, "event_id": "evt_07", "kind": "run.finished",
        "ts": "2026-07-24T12:00:01Z", "step_id": None, "agent_id": None,
        "fingerprint": None, "blobs": [],
        "payload": {
            "status": "ok",
            "totals": {
                "events": 8, "llm_calls": 1, "tool_calls": 1, "cost_usd": 0.0,
                "tokens_in": 5, "tokens_out": 3, "duration_ms": 120.0,
            },
        },
    },
]

RUN = {
    "run_id": RUN_ID, "project_id": PROJECT, "framework": "langgraph", "status": "ok",
    "started_at": "2026-07-24T12:00:00Z", "finished_at": "2026-07-24T12:00:01Z",
    "tags": {"env": "smoke"}, "totals": EVENTS[-1]["payload"]["totals"],
}

# Rollups for the catalog/Overview surfaces, derived by hand from the one
# canned run above so the fixture stays internally consistent: one project,
# one tool call, one agent, one run, zero failures.
PROJECT_ROLLUP = {
    "project_id": PROJECT, "runs": 1, "events": len(EVENTS),
    "cost_usd": 0.0, "last_seen": "2026-07-24T12:00:01Z",
}

TOOL_ROLLUP = {
    "tool_name": "web_search", "calls": 1, "errors": 0, "avg_latency_ms": 12.0,
    "side_effect_class": "external", "last_used": "2026-07-24T12:00:01Z",
}

AGENT_ROLLUP = {
    "agent_id": "plan", "events": 2, "runs": 1, "last_seen": "2026-07-24T12:00:01Z",
}

STATS = {
    "total_runs": 1, "failed_runs": 0, "active_runs": 0, "total_cost_usd": 0.0,
    "policy_denials": 0, "total_detections": 0, "window_runs": 1, "range_days": None,
    # No prior window exists behind a single seeded run, so every delta is
    # null — the same thing the real API returns rather than a bogus 0%.
    "deltas": {"runs_pct": None, "failed_runs_pct": None, "cost_pct": None},
    "daily": [{"day": "2026-07-24", "runs": 1, "failed_runs": 0, "cost_usd": 0.0}],
    "cost_by_project": [{"project_id": PROJECT, "runs": 1, "cost_usd": 0.0}],
    "recent_detections": [], "recent_policy_decisions": [],
}


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, body: object, status: int = 200) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/healthz":
            self._send_json({"status": "ok", "version": "0.1.0"})
        elif path == "/v1/runs":
            self._send_json({"runs": [RUN], "next_cursor": None})
        elif path == f"/v1/runs/{RUN_ID}":
            self._send_json(RUN)
        elif path == f"/v1/runs/{RUN_ID}/events":
            self._send_json({"events": EVENTS, "next_cursor": None})
        elif path == f"/v1/runs/{RUN_ID}/detections":
            self._send_json({"detections": [], "next_cursor": None})
        elif path == f"/v1/runs/{RUN_ID}/policy-decisions":
            self._send_json({"decisions": [], "next_cursor": None})
        elif path == "/v1/projects":
            self._send_json({"projects": [PROJECT_ROLLUP]})
        elif path == "/v1/stats":
            self._send_json(STATS)
        elif path == "/v1/events/recent":
            self._send_json({"events": EVENTS[::-1], "next_cursor": None})
        elif path == "/v1/tools":
            self._send_json({"tools": [TOOL_ROLLUP]})
        elif path == "/v1/agents":
            self._send_json({"agents": [AGENT_ROLLUP]})
        elif path == f"/v1/live/runs/{RUN_ID}":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            for event in EVENTS:
                body = json.dumps(event, separators=(",", ":"))
                self.wfile.write(f"id: {event['seq']}\ndata: {body}\n\n".encode())
                self.wfile.flush()
        elif path == "/v1/live/firehose":
            # Held open and silent: the dashboard subscribes with tail=1,
            # and this fixture's one run is already history, so a correct
            # server sends nothing. Closing instead would make EventSource
            # reconnect in a loop for the whole test.
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                while True:
                    # SSE comment frames: keep-alive that clients ignore.
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
                    time.sleep(5)
            except (BrokenPipeError, ConnectionResetError):
                return
        else:
            self._send_json({"detail": "not found", "path": path, "query": query}, status=404)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass


if __name__ == "__main__":
    server = ThreadingHTTPServer(("localhost", 8420), Handler)
    print("mock control plane on http://localhost:8420")
    server.serve_forever()
