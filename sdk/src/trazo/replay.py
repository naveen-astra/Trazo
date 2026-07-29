"""Public replay API (TRZ-P4-05, SDK.md §1, REPLAY_ENGINE.md §4).

    from trazo import replay

    session = replay.load("run_01J...", mode="strict")
    for step in session.steps():
        step.index, step.name
        step.state_before, step.state_after   # lazy blob fetch if offloaded
        step.boundary_events

    report = session.run_to()
    report.fidelity
    report.divergences

``run_to()`` re-invokes whatever callable was registered via
``@trazo.replay.entrypoint`` — trazo.replay only swaps the process
recorder into REPLAY mode around that call (``replay_recorder_scope``);
it doesn't know how any one framework wants to be built or invoked, so
the registered entrypoint must do that itself, end to end: build the
agent, wrap it with the right ``instrument()``, invoke it with the given
entry input, and return the result. Demos expose this as a standard
``build()`` factory per REPLAY_ENGINE.md §4's own wording.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from trazo.core.bundle_loader import fetch_blob
from trazo.core.bundle_loader import load_bundle as _load_bundle
from trazo.core.context import SdkConfig, config_scope
from trazo.core.recorder import Recorder, RecorderMode
from trazo.core.replay_bundle import RecordedEvent, ReplayBundle
from trazo.core.replay_report import ReplayReport
from trazo.core.runtime import replay_recorder_scope
from trazo.core.substituter import Substituter
from trazo.errors import TrazoError

_DEFAULT_ENDPOINT = "http://localhost:8420"
_DEFAULT_CACHE_DIR = Path(".trazo/cache")

_entrypoints: dict[str, Callable[[Any], Any]] = {}


class NoEntrypointRegisteredError(TrazoError):
    """Raised by ``Session.run_to()`` when no ``@entrypoint`` was
    registered for the bundle's framework (or as a default)."""

    def __init__(self, framework: str) -> None:
        super().__init__(
            f"no replay entrypoint registered for framework {framework!r} — "
            "call trazo.replay.entrypoint(fn) (optionally framework=...) "
            "before session.run_to()"
        )


def entrypoint(
    fn: Callable[[Any], Any] | None = None, *, framework: str | None = None
) -> Callable[[Any], Any]:
    """Register the callable a full-run replay (``session.run_to()``)
    re-invokes. Use directly as a decorator, or with ``framework=`` to
    scope it to bundles of that framework only (multiple entrypoints —
    e.g. one per demo — can coexist in one process this way)."""

    def register(f: Callable[[Any], Any]) -> Callable[[Any], Any]:
        _entrypoints[framework or "default"] = f
        return f

    if fn is not None:
        return register(fn)
    return register


def _registered_entrypoint(framework: str) -> Callable[[Any], Any]:
    if framework in _entrypoints:
        return _entrypoints[framework]
    if "default" in _entrypoints:
        return _entrypoints["default"]
    raise NoEntrypointRegisteredError(framework)


def _reset_entrypoints_for_tests() -> None:
    _entrypoints.clear()


class _NullShipper:
    """Never touched in normal operation: REPLAY mode ships nothing
    (Recorder.boundary/emit are both no-ops in REPLAY mode). Raises if
    somehow reached anyway, so a regression is loud, not a silent
    network call during what's supposed to be a read-only replay."""

    def enqueue(self, event: dict[str, Any]) -> None:
        raise AssertionError(
            "a replay session tried to ship a live event — "
            "Recorder.boundary()/emit() should both be no-ops in REPLAY mode"
        )

    def flush_and_stop(self, *, timeout: float = 5.0) -> None:
        pass


def _resolve_blob_field(value: Any, *, endpoint: str, cache_dir: Path) -> Any:
    """A state snapshot field is either inline JSON or ``{"$blob": sha}``
    (store_worker.py's offload shape) — resolve the latter lazily."""
    if isinstance(value, dict) and set(value) == {"$blob"}:
        return json.loads(
            fetch_blob(value["$blob"], endpoint=endpoint, cache_dir=cache_dir)
        )
    return value


class Step:
    """One framework step: its recorded state snapshots (lazy blob
    fetch) and every boundary event (llm/tool/memory) recorded within
    it (REPLAY_ENGINE.md §4)."""

    def __init__(
        self,
        *,
        index: int,
        name: str,
        started: RecordedEvent,
        finished: RecordedEvent | None,
        boundary_events: list[RecordedEvent],
        endpoint: str,
        cache_dir: Path,
    ) -> None:
        self.index = index
        self.name = name
        self._started = started
        self._finished = finished
        self.boundary_events = boundary_events
        self._endpoint = endpoint
        self._cache_dir = cache_dir

    @property
    def state_before(self) -> Any:
        return _resolve_blob_field(
            self._started.payload.get("state_before"),
            endpoint=self._endpoint,
            cache_dir=self._cache_dir,
        )

    @property
    def state_after(self) -> Any:
        if self._finished is None:
            return None
        return _resolve_blob_field(
            self._finished.payload.get("state_after"),
            endpoint=self._endpoint,
            cache_dir=self._cache_dir,
        )


def _steps_from_bundle(
    bundle: ReplayBundle, *, endpoint: str, cache_dir: Path
) -> list[Step]:
    started_events = bundle.events_by_kind("step.started")
    finished_events = bundle.events_by_kind("step.finished")
    boundary_kinds = ("llm.call", "tool.call", "memory.read", "memory.write")

    steps: list[Step] = []
    for index, started in enumerate(started_events):
        finished = finished_events[index] if index < len(finished_events) else None
        step_events = [
            event
            for kind in boundary_kinds
            for event in bundle.events_by_kind(kind)
            if event.step_id == started.step_id
        ]
        step_events.sort(key=lambda e: e.seq)
        steps.append(
            Step(
                index=index,
                name=str(started.payload.get("name", "")),
                started=started,
                finished=finished,
                boundary_events=step_events,
                endpoint=endpoint,
                cache_dir=cache_dir,
            )
        )
    return steps


class Session:
    """A loaded replay bundle, ready to inspect (``steps()``) or re-drive
    (``run_to()``)."""

    def __init__(
        self,
        bundle: ReplayBundle,
        *,
        mode: str = "strict",
        endpoint: str = _DEFAULT_ENDPOINT,
        cache_dir: Path = _DEFAULT_CACHE_DIR,
    ) -> None:
        self.bundle = bundle
        self.mode = mode
        self._endpoint = endpoint
        self._cache_dir = cache_dir

    def steps(self) -> list[Step]:
        return _steps_from_bundle(
            self.bundle, endpoint=self._endpoint, cache_dir=self._cache_dir
        )

    def run_to(self, step_index: int | None = None) -> ReplayReport:
        """Re-invoke the registered entrypoint end to end, substituting
        every boundary call from this session's bundle. ``step_index`` is
        informational only — the entrypoint runs to its own completion
        (there is no generic way to pause a re-driven framework mid-run);
        it truncates the returned report to the state as of that step
        count instead of literally stopping execution there."""
        entry = _registered_entrypoint(self.bundle.framework)
        run_started_events = self.bundle.events_by_kind("run.started")
        entry_input = (
            run_started_events[0].payload.get("entry_input")
            if run_started_events
            else None
        )

        substituter = Substituter(self.bundle, mode=self.mode)
        replay_recorder = Recorder(
            shipper=_NullShipper(), mode=RecorderMode.REPLAY, substituter=substituter
        )
        replay_config = SdkConfig(
            project=self.bundle.project_id, endpoint=self._endpoint, api_key=""
        )

        with config_scope(replay_config), replay_recorder_scope(replay_recorder):
            entry(entry_input)

        return substituter.report


def load(
    run_id: str,
    *,
    mode: str = "strict",
    endpoint: str = _DEFAULT_ENDPOINT,
    api_key: str | None = None,
    cache_dir: Path = _DEFAULT_CACHE_DIR,
) -> Session:
    """Fetch (or reuse a cached) replay bundle and return a ``Session``
    ready to inspect or re-drive."""
    bundle = _load_bundle(
        run_id, endpoint=endpoint, api_key=api_key, cache_dir=cache_dir
    )
    return Session(bundle, mode=mode, endpoint=endpoint, cache_dir=cache_dir)
