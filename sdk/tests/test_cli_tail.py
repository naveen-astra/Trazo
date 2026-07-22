"""Unit tests for trazo.cli.tail (TRZ-P2-08)."""

from __future__ import annotations

import io

import httpx

from trazo.cli.tail import _format_event, _parse_sse, tail_run


def test_parse_sse__reassembles_data_lines_into_events() -> None:
    lines = [
        "id: 0",
        'data: {"seq":0,"kind":"run.started"}',
        "",
        "id: 1",
        'data: {"seq":1,"kind":"run.finished"}',
        "",
    ]

    events = list(_parse_sse(lines))

    assert events == [
        {"seq": 0, "kind": "run.started"},
        {"seq": 1, "kind": "run.finished"},
    ]


def test_parse_sse__yields_a_trailing_event_with_no_final_blank_line() -> None:
    lines = ["id: 0", 'data: {"seq":0,"kind":"run.started"}']

    events = list(_parse_sse(lines))

    assert events == [{"seq": 0, "kind": "run.started"}]


def test_format_event__renders_seq_step_agent_kind() -> None:
    line = _format_event(
        {
            "seq": 3,
            "ts": "2026-01-01T00:00:00Z",
            "step_id": "step_1",
            "agent_id": "agent_1",
            "kind": "tool.call",
        }
    )

    assert "3" in line
    assert "step=step_1" in line
    assert "agent=agent_1" in line
    assert "tool.call" in line


def test_format_event__renders_dash_for_missing_step_and_agent() -> None:
    line = _format_event(
        {"seq": 0, "ts": "t", "step_id": None, "agent_id": None, "kind": "run.started"}
    )

    assert "step=-" in line
    assert "agent=-" in line


def test_tail_run__prints_each_event_and_returns_0_when_run_finishes() -> None:
    started = '{"seq":0,"kind":"run.started","ts":"t","step_id":null,"agent_id":null}'
    finished = '{"seq":1,"kind":"run.finished","ts":"t","step_id":null,"agent_id":null}'
    body = f"id: 0\ndata: {started}\n\nid: 1\ndata: {finished}\n\n".encode()

    def handler(request: httpx.Request) -> httpx.Response:
        headers = {"content-type": "text/event-stream"}
        return httpx.Response(200, content=body, headers=headers)

    out = io.StringIO()
    exit_code = tail_run(
        "run_1",
        endpoint="http://example.test",
        out=out,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert exit_code == 0
    printed = out.getvalue()
    assert "run.started" in printed
    assert "run.finished" in printed


def test_tail_run__returns_1_on_non_200() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    out = io.StringIO()
    exit_code = tail_run(
        "run_1",
        endpoint="http://example.test",
        out=out,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert exit_code == 1


def test_tail_run__returns_1_on_connection_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    out = io.StringIO()
    exit_code = tail_run(
        "run_1",
        endpoint="http://example.test",
        out=out,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert exit_code == 1
