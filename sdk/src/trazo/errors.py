"""Typed exceptions for the SDK (CODING_STANDARDS.md §1).

AGENTS.md's hard rule: the SDK must never crash the host agent during a
run. The only exceptions it raises into user code during a run are
PolicyDenied and ReplayDivergence (added in later phases). NotInitializedError
is a setup-time contract violation (calling the SDK before ``trazo.init``),
not a runtime crash — raising clearly here is correct, not a violation.
"""

from __future__ import annotations


class TrazoError(Exception):
    """Root of every SDK-raised exception."""


class NotInitializedError(TrazoError):
    """Raised when SDK functionality is used before ``trazo.init()``."""

    def __init__(self) -> None:
        super().__init__("trazo.init(project=...) must be called before using the SDK")


class NoActiveRunError(TrazoError):
    """Raised when the recorder is used outside an active ``run_scope``."""

    def __init__(self) -> None:
        super().__init__(
            "no active run — call within `with trazo.core.context.run_scope(...)`"
        )


class ReplayNotConfiguredError(TrazoError):
    """Raised when a Recorder in REPLAY mode has no Substituter attached —
    a setup-time contract violation (TRZ-P4-02), not a replay divergence."""


class PolicyDenied(TrazoError):
    """Raised by ``PolicyHook.check()`` (TRZ-P6-04, ADR-006) on a deny or
    escalate decision while in ``enforce`` mode. Callers must let this
    propagate uncaught — the governed action has not executed yet, and
    swallowing this exception is exactly how a blocked call would end up
    running anyway."""

    def __init__(self, *, decision: str, policy_id: str, reasons: list[str]) -> None:
        reason_text = "; ".join(reasons) if reasons else "no reason given"
        super().__init__(f"policy {policy_id!r} {decision}: {reason_text}")
        self.decision = decision
        self.policy_id = policy_id
        self.reasons = reasons
