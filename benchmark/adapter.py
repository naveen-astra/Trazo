"""TrazoBench adapter interfaces (TRZ-P7-01, RESEARCH.md RQ3).

Small ``Protocol``s any tool -- Trazo's own or a third party's -- can
implement to be scored by TrazoBench's runners:

    detect(events) -> list[Detection]                 # RQ2/detection
    replay(run_id, endpoint=...) -> dict[str, Any]     # RQ1/fidelity

Deliberately not ``trazo_server.detectors.base.Detector``'s per-event/
window Protocol: that one is shaped for the *online* ``DetectorWorker``'s
one-event-at-a-time dispatch and hands each detector a ``RunWindow`` it
never builds itself. A third party scoring their own tool against
TrazoBench shouldn't have to reimplement that bookkeeping just to be
scored at all -- handing over the whole run's events and getting back
every ``Detection`` found is the smallest surface that still lets the
runner compute precision/recall/FPR/latency (RESEARCH.md RQ2/RQ3).

Latency scoring needs to know *which event* a detection fired at, but
``Detection`` (``trazo_server.detectors.base``) carries no seq of its
own -- only ``evidence_event_ids``. Every shipped detector includes the
triggering event's own id last in that list (it's appended to
``RunWindow.recent_boundaries``, in arrival order, before the detector
runs), so the runner recovers the fire point by mapping
``evidence_event_ids`` back to seqs via the same event list it handed
to ``detect()``, rather than the adapter interface carrying an extra
online-only field.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Protocol

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CONTROL_PLANE_SRC = _REPO_ROOT / "control-plane" / "src"
sys.path.insert(0, str(_CONTROL_PLANE_SRC))

from trazo_server.detectors.base import (  # noqa: E402
    Detection,
    Detector,
    RunWindow,
)
from trazo_server.detectors.budget import BudgetDetector  # noqa: E402
from trazo_server.detectors.loop import LoopDetector  # noqa: E402
from trazo_server.detectors.thrash import ThrashDetector  # noqa: E402
from trazo_server.drift import DriftDetector  # noqa: E402
from trazo_server.events import Event  # noqa: E402


class DetectionAdapter(Protocol):
    """Implement this against your own tool to be scored by TrazoBench's
    detection runner."""

    def detect(self, events: list[Event]) -> list[Detection]: ...


class TrazoDetectorAdapter:
    """Reference ``DetectionAdapter``: Trazo's own online detectors
    (Loop/Budget/Thrash by default), run through the identical
    ``RunWindow``-driven dispatch ``DetectorWorker._handle_event`` uses
    online -- this is where TrazoBench's own (non-baseline) numbers come
    from, not a separate offline-only reimplementation."""

    def __init__(
        self,
        detectors: list[Detector] | None = None,
        *,
        run_id: str = "bench",
        drift: DriftDetector | None = None,
    ) -> None:
        self._detectors = (
            detectors
            if detectors is not None
            else [LoopDetector(), BudgetDetector(), ThrashDetector()]
        )
        self._run_id = run_id
        # Opt-in: asks a model, so it is scored apart from the rule
        # detectors (benchmark/detection/drift_runner.py).
        self._drift = drift

    def detect(self, events: list[Event]) -> list[Detection]:
        window = RunWindow(self._run_id)
        found: list[Detection] = []
        if self._drift is not None:
            self._drift.forget(self._run_id)
        for event in sorted(events, key=lambda e: e.seq):
            window.record(event)
            for detector in self._detectors:
                detection = detector.on_event(event, window)
                if detection is not None:
                    found.append(detection)
            if self._drift is not None:
                drift_detection = self._drift.evaluate(event, window)
                if drift_detection is not None:
                    found.append(drift_detection)
        return found


class RandomFlaggerAdapter:
    """The RQ3 baseline: flags a fixed fraction of boundary events, with
    no regard for their content, to anchor the scale (RESEARCH.md's
    "trivial baseline (random flagger)") -- what precision/recall a
    detector that isn't actually detecting anything would score.

    Deterministic given ``(run_id, event_id)`` rather than seeded from
    wall-clock or call order: reruns of the same corpus must reproduce
    the same flagged events for the baseline numbers to be reproducible
    at all, which a ``random.Random`` instance advanced call-by-call
    would not survive a detector ordering change.
    """

    _BOUNDARY_KINDS = frozenset(
        {"llm.call", "tool.call", "memory.read", "memory.write", "human.checkpoint"}
    )

    def __init__(self, *, flag_rate: float = 0.05) -> None:
        if not 0.0 <= flag_rate <= 1.0:
            raise ValueError(f"flag_rate must be in [0, 1], got {flag_rate}")
        self._flag_rate = flag_rate

    def _should_flag(self, event: Event) -> bool:
        digest = hashlib.sha256(event.event_id.encode("utf-8")).digest()
        # First 4 bytes as a uniform-ish float in [0, 1) -- avoids a
        # dependency on `random` (whose output isn't guaranteed stable
        # across Python versions) for something that must reproduce
        # identically forever once a baseline number is published.
        as_fraction = int.from_bytes(digest[:4], "big") / 2**32
        return as_fraction < self._flag_rate

    def detect(self, events: list[Event]) -> list[Detection]:
        found: list[Detection] = []
        for event in sorted(events, key=lambda e: e.seq):
            if event.kind not in self._BOUNDARY_KINDS:
                continue
            if not self._should_flag(event):
                continue
            found.append(
                Detection(
                    detector="random_flagger",
                    severity="info",
                    evidence_event_ids=[event.event_id],
                    details={"flag_rate": self._flag_rate},
                    window={},
                )
            )
        return found


class ReplayAdapter(Protocol):
    """Implement this to register a new project's replay tool for
    ``benchmark/fidelity/run_harness.py`` (RQ1/RQ3).

    Not literally ``replay(bundle) -> report`` (RESEARCH.md's shorthand):
    ``trazo.replay.Session.run_to()`` needs a *registered entrypoint*
    per framework to re-invoke (building the agent, wrapping it with the
    right ``instrument()``, invoking it) -- there is no generic way to
    replay a bundle without framework-specific re-invocation code, so
    "the bundle" isn't actually a self-sufficient input here the way a
    detector's event list is. What every replay tool this harness can
    score *does* share: given a corpus entry's ``run_id`` and a live
    control-plane endpoint to fetch it from, produce a report shaped
    like ``trazo verify --json``'s own stable, documented output
    (REPLAY_ENGINE.md) -- ``boundary_fidelity``, ``state_fidelity``,
    ``replay_overhead``, ``divergences``.
    """

    def replay(self, run_id: str, *, endpoint: str) -> dict[str, Any]: ...


class SubprocessReplayAdapter:
    """Reference ReplayAdapter for Trazo's own demos: invokes a demo's
    own ``replay_entrypoint.py <run_id> --endpoint ... --json`` in its
    own subprocess (never both demos' same-named ``llm``/``agent``
    modules in one interpreter -- see each entrypoint script's own
    docstring) and parses its ``trazo verify``-shaped JSON report."""

    def __init__(self, command: list[str]) -> None:
        self._command = command

    def replay(self, run_id: str, *, endpoint: str) -> dict[str, Any]:
        completed = subprocess.run(
            [*self._command, run_id, "--endpoint", endpoint, "--json"],
            capture_output=True,
            text=True,
            cwd=_REPO_ROOT,
            check=False,
        )
        result: dict[str, Any] = json.loads(completed.stdout)
        return result
