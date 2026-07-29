"""PolicyHook: synchronous pre-action governance check (TRZ-P6-04,
ADR-006, SDK.md §4).

The adapter calls ``PolicyHook.check(...)`` immediately before executing
any governed action. This module owns the "which actions are governed"
scope decision (default: ``side_effect_class in {write, external}``,
extendable via ``TRAZO_POLICY_SCOPE``) so an adapter can call ``check()``
unconditionally on every tool.call and let this decide whether there's
anything to do.

A deny/escalate decision in ``enforce`` mode raises ``PolicyDenied``,
which the caller MUST let propagate uncaught — that is what makes "the
blocked call never executes" true; catching and swallowing it here
would silently defeat governance (AGENTS.md: the SDK's only two
during-a-run exceptions are ``PolicyDenied`` and ``ReplayDivergence``).

Holds one ``httpx.Client`` for its entire lifetime rather than opening
one per ``check()`` call — the control-plane side of this feature
(TRZ-P6-03's ``HttpOpaClient``) measured a fresh ``httpx.Client``/
``AsyncClient`` costing ~180ms in construction/teardown alone on this
stack, which would blow the 150ms budget on every single governed
action if this made the same mistake. Call ``close()`` on shutdown
(``trazo.shutdown()`` does this).

``run_context.active_detections`` is always sent empty: the SDK has no
current mechanism to learn which detections the control plane has
raised for this run (detections are discovered server-side, TRZ-P5-06,
with no push channel back to the SDK) — the active-detection-gate
policy (TRZ-P6-02) can't fire through the SDK's own policy calls yet.
Flagged here rather than silently pretended-away; wiring that up is a
follow-on (the SDK would need to poll or subscribe to its own run's
detections before each governed call).
"""

from __future__ import annotations

import os
from enum import Enum
from typing import Any

import httpx
import structlog

from trazo.core.context import current_run_context
from trazo.core.fingerprint import fingerprint_for
from trazo.errors import NoActiveRunError, PolicyDenied

log = structlog.get_logger(__name__)

_DEFAULT_GOVERNED_SIDE_EFFECT_CLASSES = frozenset({"write", "external"})
_EVALUATE_PATH = "/v1/policy/evaluate"
_DECIDED_STATES_THAT_BLOCK = frozenset({"deny", "escalate"})


class PolicyMode(str, Enum):
    OFF = "off"
    OBSERVE = "observe"
    ENFORCE = "enforce"


class PolicyFail(str, Enum):
    OPEN = "open"
    CLOSED = "closed"


def _governed_side_effect_classes_from_env() -> frozenset[str]:
    extra = os.environ.get("TRAZO_POLICY_SCOPE", "")
    extras = {s.strip() for s in extra.split(",") if s.strip()}
    return _DEFAULT_GOVERNED_SIDE_EFFECT_CLASSES | extras


def _mode_from_env() -> PolicyMode:
    raw = os.environ.get("TRAZO_POLICY_MODE", "off")
    try:
        return PolicyMode(raw)
    except ValueError:
        log.warning("policy.invalid_mode_env", value=raw)
        return PolicyMode.OFF


def _fail_from_env() -> PolicyFail:
    raw = os.environ.get("TRAZO_POLICY_FAIL", "open")
    try:
        return PolicyFail(raw)
    except ValueError:
        log.warning("policy.invalid_fail_env", value=raw)
        return PolicyFail.OPEN


class PolicyHook:
    """One instance per ``trazo.init()`` call; adapters call ``check()``."""

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        mode: PolicyMode | None = None,
        fail: PolicyFail | None = None,
        governed_side_effect_classes: frozenset[str] | None = None,
        timeout_seconds: float = 0.15,
        client: httpx.Client | None = None,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._api_key = api_key
        self.mode = mode if mode is not None else _mode_from_env()
        self.fail = fail if fail is not None else _fail_from_env()
        self._governed = (
            governed_side_effect_classes
            if governed_side_effect_classes is not None
            else _governed_side_effect_classes_from_env()
        )
        self._client = client or httpx.Client(timeout=timeout_seconds)
        # fingerprint -> (decision, policy_id, reasons); one PolicyHook per
        # trazo.init() call, so this is naturally scoped to one run.
        self._cache: dict[str, tuple[str, str, list[str]]] = {}

    def check(
        self,
        *,
        kind: str,
        tool_name: str | None,
        args: dict[str, Any],
        side_effect_class: str,
        projected_cost_usd: float = 0.0,
    ) -> None:
        """No-op in ``off`` mode or outside the governed scope. Raises
        ``PolicyDenied`` on a deny/escalate decision while in ``enforce``
        mode — never in ``observe`` (which still evaluates and records,
        per ADR-006, just never blocks)."""
        if self.mode is PolicyMode.OFF:
            return
        if side_effect_class not in self._governed:
            return

        ctx = current_run_context()
        if ctx is None:
            raise NoActiveRunError()

        fingerprint = fingerprint_for(kind, {"tool_name": tool_name, "args": args})

        cached = self._cache.get(fingerprint)
        if cached is not None:
            decision, policy_id, reasons = cached
        else:
            decision, policy_id, reasons = self._evaluate(
                run_id=ctx.run_id,
                project=ctx.project,
                kind=kind,
                fingerprint=fingerprint,
                tool_name=tool_name,
                side_effect_class=side_effect_class,
                projected_cost_usd=projected_cost_usd,
                cost_usd_so_far=ctx.totals.cost_usd,
            )
            self._cache[fingerprint] = (decision, policy_id, reasons)

        if decision in _DECIDED_STATES_THAT_BLOCK and self.mode is PolicyMode.ENFORCE:
            raise PolicyDenied(decision=decision, policy_id=policy_id, reasons=reasons)

    def _evaluate(
        self,
        *,
        run_id: str,
        project: str,
        kind: str,
        fingerprint: str,
        tool_name: str | None,
        side_effect_class: str,
        projected_cost_usd: float,
        cost_usd_so_far: float,
    ) -> tuple[str, str, list[str]]:
        body = {
            "run_id": run_id,
            "project": project,
            "mode": self.mode.value,
            "action": {
                "kind": kind,
                "fingerprint": fingerprint,
                "tool_name": tool_name,
                "side_effect_class": side_effect_class,
                "projected_cost_usd": projected_cost_usd,
            },
            "run_context": {
                "cost_usd_so_far": cost_usd_so_far,
                "active_detections": [],
            },
        }
        try:
            response = self._client.post(
                f"{self._endpoint}{_EVALUATE_PATH}",
                json=body,
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            return self._fail_decision(exc)

        result = response.json()
        return (
            str(result.get("decision", "allow")),
            str(result.get("policy_id", "")),
            [str(r) for r in result.get("reasons", [])],
        )

    def _fail_decision(self, exc: Exception) -> tuple[str, str, list[str]]:
        """TRAZO_POLICY_FAIL governs behavior when the control plane's
        policy endpoint is unreachable or times out (ADR-006) — the
        control plane's own OPA-unreachable case is a separate concern
        (a 503 the SDK sees as exactly this kind of failure)."""
        if self.fail is PolicyFail.CLOSED:
            log.warning("policy.fail_closed", error=str(exc))
            return "deny", "fail-closed", [f"policy endpoint unreachable: {exc}"]
        log.warning("policy.fail_open", error=str(exc))
        return "allow", "", []

    def close(self) -> None:
        self._client.close()
