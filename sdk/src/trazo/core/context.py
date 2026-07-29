"""Run/step execution context and SDK configuration (TRZ-P2-01).

Contextvars carry run_id, the enclosing step stack, and the current
agent_id so adapters and the recorder (P2-03) don't thread these through
every call — they propagate correctly across threads and asyncio tasks
without extra plumbing (SDK.md §2 "Context (contextvars)").

The per-run seq counter is a separate, explicitly shared mutable object
(not itself a contextvar): a contextvar copied into a new thread/task gets
an independent *reference*, but that reference points at the same
_SeqCounter instance, so seq stays a single strictly-increasing sequence
for the whole run even when multiple threads/tasks touch it concurrently
(EVENTS.md §1: "seq is strictly increasing per run").
"""

from __future__ import annotations

import contextvars
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from trazo.core.ulid import new_run_id, new_step_id
from trazo.errors import NotInitializedError


@dataclass(frozen=True)
class SdkConfig:
    """Resolved SDK configuration, set once by ``trazo.init``."""

    project: str
    endpoint: str
    api_key: str


_config: SdkConfig | None = None


def init(
    *, project: str, endpoint: str = "http://localhost:8420", api_key: str | None = None
) -> None:
    """Configure the SDK (SDK.md §1). Call once, at process startup.

    Calling again replaces the config — last call wins; useful in tests,
    but production code should call this exactly once.
    """
    global _config
    resolved_key = (
        api_key if api_key is not None else os.environ.get("TRAZO_API_KEY", "")
    )
    _config = SdkConfig(project=project, endpoint=endpoint, api_key=resolved_key)


def get_config() -> SdkConfig:
    """Return the resolved config; raises NotInitializedError before init()."""
    if _config is None:
        raise NotInitializedError()
    return _config


@contextmanager
def config_scope(config: SdkConfig) -> Iterator[None]:
    """Temporarily install ``config``, restoring whatever was there before
    on exit (TRZ-P4-07) — used by ``trazo.replay`` so a replay session's
    re-driven adapter code (which calls ``get_config().project`` just
    like a live run does) works without a real ``trazo.init()`` having
    been called in this process, and without disturbing one that has."""
    global _config
    previous = _config
    _config = config
    try:
        yield
    finally:
        _config = previous


def is_initialized() -> bool:
    return _config is not None


def _reset_config_for_tests() -> None:
    """Test-only: clear global config so each test starts uninitialized."""
    global _config
    _config = None


class _SeqCounter:
    """Thread-safe strictly-increasing per-run sequence counter, 0-based."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._value = -1

    def next(self) -> int:
        with self._lock:
            self._value += 1
            return self._value


@dataclass
class RunContext:
    """One run's identity and seq counter; held by _run_context_var."""

    run_id: str
    project: str
    _seq_counter: _SeqCounter = field(default_factory=_SeqCounter)

    def next_seq(self) -> int:
        return self._seq_counter.next()


_run_context_var: contextvars.ContextVar[RunContext | None] = contextvars.ContextVar(
    "trazo_run_context", default=None
)
_step_stack_var: contextvars.ContextVar[tuple[str, ...]] = contextvars.ContextVar(
    "trazo_step_stack", default=()
)
_agent_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "trazo_agent_id", default=None
)


def current_run_context() -> RunContext | None:
    return _run_context_var.get()


def current_run_id() -> str | None:
    ctx = current_run_context()
    return ctx.run_id if ctx is not None else None


def current_step_id() -> str | None:
    stack = _step_stack_var.get()
    return stack[-1] if stack else None


def current_agent_id() -> str | None:
    return _agent_id_var.get()


class run_scope:
    """Context manager establishing a fresh run context (new seq counter)."""

    def __init__(self, project: str, *, run_id: str | None = None) -> None:
        self._project = project
        self._run_id = run_id or new_run_id()
        self._token: contextvars.Token[RunContext | None] | None = None

    def __enter__(self) -> RunContext:
        ctx = RunContext(run_id=self._run_id, project=self._project)
        self._token = _run_context_var.set(ctx)
        return ctx

    def __exit__(self, *exc_info: object) -> None:
        if self._token is not None:
            _run_context_var.reset(self._token)


class step_scope:
    """Context manager pushing one step_id onto the step stack for its
    duration — nested calls stack correctly; ``current_step_id()`` always
    reports the innermost active step."""

    def __init__(self, step_id: str | None = None) -> None:
        self._step_id = step_id or new_step_id()
        self._token: contextvars.Token[tuple[str, ...]] | None = None

    def __enter__(self) -> str:
        stack = _step_stack_var.get()
        self._token = _step_stack_var.set((*stack, self._step_id))
        return self._step_id

    def __exit__(self, *exc_info: object) -> None:
        if self._token is not None:
            _step_stack_var.reset(self._token)


class agent_scope:
    """Context manager setting the current agent_id for its duration."""

    def __init__(self, agent_id: str) -> None:
        self._agent_id = agent_id
        self._token: contextvars.Token[str | None] | None = None

    def __enter__(self) -> str:
        self._token = _agent_id_var.set(self._agent_id)
        return self._agent_id

    def __exit__(self, *exc_info: object) -> None:
        if self._token is not None:
            _agent_id_var.reset(self._token)


class optional_step_scope:
    """``step_scope`` that no-ops when there's no enclosing step to
    attribute to — every adapter's boundary-event handlers hit this case
    (a boundary observed with no step correlation available)."""

    def __init__(self, step_id: str | None) -> None:
        self._inner = step_scope(step_id) if step_id is not None else None

    def __enter__(self) -> None:
        if self._inner is not None:
            self._inner.__enter__()

    def __exit__(self, *exc_info: object) -> None:
        if self._inner is not None:
            self._inner.__exit__(*exc_info)


class optional_agent_scope:
    """``agent_scope`` that no-ops when there's no agent to attribute to."""

    def __init__(self, agent_id: str | None) -> None:
        self._inner = agent_scope(agent_id) if agent_id is not None else None

    def __enter__(self) -> None:
        if self._inner is not None:
            self._inner.__enter__()

    def __exit__(self, *exc_info: object) -> None:
        if self._inner is not None:
            self._inner.__exit__(*exc_info)
