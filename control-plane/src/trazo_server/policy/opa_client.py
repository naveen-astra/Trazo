"""The OpaClient port: one call, evaluate an action against the bundle
loaded at `data.trazo.decision` (TRZ-P6-03).

``HttpOpaClient`` is the MVP implementation (a real OPA sidecar, ADR-006);
an in-memory fake implements the same Protocol for unit tests that don't
need a live OPA process.
"""

from __future__ import annotations

from typing import Any, Protocol

import httpx

from trazo_server.errors import OpaUnavailableError

DECISION_PATH = "/v1/data/trazo/decision"


class OpaClient(Protocol):
    """Evaluates one action against the loaded policy bundle."""

    async def evaluate(self, input_doc: dict[str, Any]) -> dict[str, Any]:
        """Return the bundle's `data.trazo.decision` document (`decision`/
        `policy_id`/`reasons`, plus whatever internal helper rules the
        bundle happens to also compute) for `input_doc`.

        Raises ``OpaUnavailableError`` on timeout, connection failure, or
        a non-2xx response — never lets an OPA-side problem surface as
        some other exception type the caller has to guess at.
        """
        ...


class HttpOpaClient:
    """Implements OpaClient over a real OPA sidecar's HTTP data API.

    Holds one ``httpx.AsyncClient`` for its entire lifetime rather than
    opening one per ``evaluate()`` call — measured directly against a
    real local OPA process (TRZ-P6-03): a fresh ``AsyncClient`` per call
    costs ~180ms in *client construction/teardown alone* on this stack
    (nothing to do with the network round trip, which is ~2ms warm),
    which by itself blows the 150ms budget on every single request. A
    long-lived client with its connection pool amortizes that cost to
    near zero after the first call. Call ``aclose()`` on app shutdown.

    ``transport`` is injectable (an ``httpx.MockTransport`` in unit
    tests) so the request/response contract can be exercised without a
    live OPA process — production callers never pass it, and get a real
    network-backed client.
    """

    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float = 0.15,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout_seconds, transport=transport)

    async def evaluate(self, input_doc: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._client.post(
                f"{self._base_url}{DECISION_PATH}",
                json={"input": input_doc},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise OpaUnavailableError(f"OPA request failed: {exc}") from exc

        body = response.json()
        result = body.get("result")
        if not isinstance(result, dict):
            raise OpaUnavailableError(
                f"OPA returned no result document for {DECISION_PATH}"
            )
        return result

    async def aclose(self) -> None:
        await self._client.aclose()


class FakeOpaClient:
    """Scriptable OpaClient fake for unit tests that don't need a live OPA
    process — set ``.next_result`` to whatever `data.trazo.decision`
    document the test wants back, or ``.raise_unavailable`` to exercise
    the failure path. Records every ``input_doc`` it was called with."""

    def __init__(self, *, next_result: dict[str, Any] | None = None) -> None:
        self.next_result = next_result or {
            "decision": "allow",
            "policy_id": "",
            "reasons": [],
        }
        self.raise_unavailable = False
        self.calls: list[dict[str, Any]] = []

    async def evaluate(self, input_doc: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(input_doc)
        if self.raise_unavailable:
            raise OpaUnavailableError("simulated OPA unavailability")
        return self.next_result
