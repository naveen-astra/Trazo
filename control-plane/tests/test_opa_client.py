"""Unit tests for HttpOpaClient (TRZ-P6-03), against a mocked transport --
no live OPA process needed. test_opa_client_integration.py covers the
real-process path."""

from __future__ import annotations

import httpx
import pytest

from trazo_server.errors import OpaUnavailableError
from trazo_server.policy.opa_client import DECISION_PATH, HttpOpaClient


def _client(handler: httpx.MockTransport) -> HttpOpaClient:
    return HttpOpaClient(base_url="http://opa.test", transport=handler)


async def test_evaluate__posts_input_and_returns_the_result_document() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200, json={"result": {"decision": "deny", "policy_id": "cost_cap"}}
        )

    client = _client(httpx.MockTransport(handler))

    result = await client.evaluate({"run_id": "run_1"})

    assert result == {"decision": "deny", "policy_id": "cost_cap"}
    assert seen[0].url.path == DECISION_PATH
    assert seen[0].method == "POST"


async def test_evaluate__raises_opa_unavailable_on_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("simulated timeout", request=request)

    client = _client(httpx.MockTransport(handler))

    with pytest.raises(OpaUnavailableError):
        await client.evaluate({"run_id": "run_1"})


async def test_evaluate__raises_opa_unavailable_on_non_2xx() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(500, json={"error": "internal"})

    client = _client(httpx.MockTransport(handler))

    with pytest.raises(OpaUnavailableError):
        await client.evaluate({"run_id": "run_1"})


async def test_evaluate__raises_opa_unavailable_when_result_is_missing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"not_result": {}})

    client = _client(httpx.MockTransport(handler))

    with pytest.raises(OpaUnavailableError):
        await client.evaluate({"run_id": "run_1"})
