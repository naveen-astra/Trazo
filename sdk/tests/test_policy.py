"""Unit tests for PolicyHook (TRZ-P6-04)."""

from __future__ import annotations

import json

import httpx
import pytest

from trazo.core.context import run_scope
from trazo.core.policy import PolicyFail, PolicyHook, PolicyMode
from trazo.errors import PolicyDenied


def _hook(handler, **kwargs) -> PolicyHook:  # type: ignore[no-untyped-def]
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return PolicyHook(
        endpoint="http://example.test", api_key="k", client=client, **kwargs
    )


def _allow_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200, json={"decision": "allow", "policy_id": "", "reasons": []}
    )


def _deny_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={"decision": "deny", "policy_id": "cost_cap", "reasons": ["over cap"]},
    )


def test_check__off_mode_never_calls_the_endpoint() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"decision": "deny"})

    hook = _hook(handler, mode=PolicyMode.OFF)
    with run_scope("proj"):
        hook.check(
            kind="tool.call", tool_name="x", args={}, side_effect_class="external"
        )

    assert calls == []


def test_check__ungoverned_side_effect_class_never_calls_the_endpoint() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"decision": "deny"})

    hook = _hook(handler, mode=PolicyMode.ENFORCE)
    with run_scope("proj"):
        hook.check(kind="tool.call", tool_name="x", args={}, side_effect_class="read")

    assert calls == []


def test_check__allow_decision_does_not_raise() -> None:
    hook = _hook(_allow_handler, mode=PolicyMode.ENFORCE)
    with run_scope("proj"):
        hook.check(
            kind="tool.call", tool_name="x", args={}, side_effect_class="external"
        )


def test_check__deny_decision_raises_policy_denied_in_enforce_mode() -> None:
    hook = _hook(_deny_handler, mode=PolicyMode.ENFORCE)
    with run_scope("proj"), pytest.raises(PolicyDenied) as exc_info:
        hook.check(
            kind="tool.call", tool_name="x", args={}, side_effect_class="external"
        )

    assert exc_info.value.decision == "deny"
    assert exc_info.value.policy_id == "cost_cap"
    assert exc_info.value.reasons == ["over cap"]


def test_check__deny_decision_does_not_raise_in_observe_mode() -> None:
    hook = _hook(_deny_handler, mode=PolicyMode.OBSERVE)
    with run_scope("proj"):
        hook.check(
            kind="tool.call", tool_name="x", args={}, side_effect_class="external"
        )


def test_check__escalate_decision_also_raises_in_enforce_mode() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"decision": "escalate", "policy_id": "x", "reasons": ["r"]}
        )

    hook = _hook(handler, mode=PolicyMode.ENFORCE)
    with run_scope("proj"), pytest.raises(PolicyDenied) as exc_info:
        hook.check(
            kind="tool.call", tool_name="x", args={}, side_effect_class="external"
        )

    assert exc_info.value.decision == "escalate"


def test_check__second_call_with_the_same_fingerprint_is_cached() -> None:
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={"decision": "allow"})

    hook = _hook(handler, mode=PolicyMode.ENFORCE)
    with run_scope("proj"):
        hook.check(
            kind="tool.call",
            tool_name="x",
            args={"a": 1},
            side_effect_class="external",
        )
        hook.check(
            kind="tool.call",
            tool_name="x",
            args={"a": 1},
            side_effect_class="external",
        )

    assert call_count == 1


def test_check__different_args_are_not_cached_together() -> None:
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={"decision": "allow"})

    hook = _hook(handler, mode=PolicyMode.ENFORCE)
    with run_scope("proj"):
        hook.check(
            kind="tool.call", tool_name="x", args={"a": 1}, side_effect_class="external"
        )
        hook.check(
            kind="tool.call", tool_name="x", args={"a": 2}, side_effect_class="external"
        )

    assert call_count == 2


def test_check__fails_open_on_timeout_by_default() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("simulated timeout", request=request)

    hook = _hook(handler, mode=PolicyMode.ENFORCE, fail=PolicyFail.OPEN)
    with run_scope("proj"):
        hook.check(
            kind="tool.call", tool_name="x", args={}, side_effect_class="external"
        )  # must not raise


def test_check__fails_closed_on_timeout_when_configured() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("simulated timeout", request=request)

    hook = _hook(handler, mode=PolicyMode.ENFORCE, fail=PolicyFail.CLOSED)
    with run_scope("proj"), pytest.raises(PolicyDenied) as exc_info:
        hook.check(
            kind="tool.call", tool_name="x", args={}, side_effect_class="external"
        )

    assert exc_info.value.decision == "deny"
    assert exc_info.value.policy_id == "fail-closed"


def test_check__request_body_matches_the_api_contract() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"decision": "allow"})

    hook = _hook(handler, mode=PolicyMode.ENFORCE)
    with run_scope("proj"):
        hook.check(
            kind="tool.call",
            tool_name="send_email",
            args={"to": "x@example.com"},
            side_effect_class="external",
            projected_cost_usd=0.4,
        )

    [body] = seen
    assert body["run_id"]
    assert body["project"] == "proj"
    assert body["mode"] == "enforce"
    assert body["action"]["kind"] == "tool.call"
    assert body["action"]["tool_name"] == "send_email"
    assert body["action"]["side_effect_class"] == "external"
    assert body["action"]["projected_cost_usd"] == 0.4
    assert body["action"]["fingerprint"].startswith("sha256:")
    assert body["run_context"]["active_detections"] == []


def test_check__custom_scope_governs_additional_side_effect_classes() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"decision": "allow"})

    hook = _hook(
        handler,
        mode=PolicyMode.ENFORCE,
        governed_side_effect_classes=frozenset({"write", "external", "read"}),
    )
    with run_scope("proj"):
        hook.check(kind="tool.call", tool_name="x", args={}, side_effect_class="read")

    assert len(calls) == 1
