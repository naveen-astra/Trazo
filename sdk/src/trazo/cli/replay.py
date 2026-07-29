"""``trazo replay <run_id>`` / ``trazo verify <run_id>`` (SDK.md §5,
REPLAY_ENGINE.md §5-6).

``replay`` re-drives a run under the caller's chosen mode and shows
whatever the Substituter found — including stopping at the first
divergence in ``strict`` mode, since that's the whole point of picking
strict for a debugging session. ``verify`` always re-drives leniently
internally (regardless of any one divergence) so it can report the full
three-metric fidelity picture — boundary fidelity, state fidelity,
replay overhead — even on a run that doesn't fully match anymore; the
listed divergences are exactly where it didn't.
"""

from __future__ import annotations

import json as json_module
import sys
import time
from pathlib import Path
from typing import Any, TextIO

from trazo import replay as replay_module
from trazo.core.bundle_loader import BundleFetchError
from trazo.core.replay_bundle import ReplayBundle
from trazo.core.replay_report import ReplayDivergence, ReplayReport

_DEFAULT_CACHE_DIR = Path(".trazo/cache")


def _divergence_summary(divergence: ReplayDivergence) -> dict[str, Any]:
    detail = divergence.detail
    return {
        "kind": divergence.kind,
        "reason": divergence.reason,
        "expected_seq": detail.expected_seq,
        "expected_event_id": detail.expected_event_id,
        "expected_fingerprint": detail.expected_fingerprint,
        "live_fingerprint": detail.live_fingerprint,
    }


def _report_summary(report: ReplayReport) -> dict[str, Any]:
    return {
        "boundary_fidelity": report.fidelity,
        "state_fidelity": report.state_fidelity,
        "matched": len(report.steps),
        "reordered": report.reordered_count,
        "divergences": [_divergence_summary(d) for d in report.divergences],
    }


def _print_report(
    summary: dict[str, Any], *, run_id: str, framework: str, mode: str, out: TextIO
) -> None:
    print(f"run {run_id} ({framework}), mode={mode}", file=out)
    print(f"  boundary fidelity: {summary['boundary_fidelity']:.2%}", file=out)
    print(f"  state fidelity:    {summary['state_fidelity']:.2%}", file=out)
    print(
        f"  matched: {summary['matched']}  reordered: {summary['reordered']}  "
        f"divergences: {len(summary['divergences'])}",
        file=out,
    )
    for d in summary["divergences"]:
        print(
            f"    - {d['kind']} ({d['reason']}) expected seq={d['expected_seq']} "
            f"event={d['expected_event_id']}",
            file=out,
        )


def run_replay(
    run_id: str,
    *,
    mode: str = "strict",
    step: int | None = None,
    endpoint: str,
    api_key: str | None = None,
    cache_dir: Path = _DEFAULT_CACHE_DIR,
    out: TextIO = sys.stdout,
    as_json: bool = False,
) -> int:
    """Re-drive ``run_id`` under ``mode``. Returns 0 if the replay
    completed with zero divergences, 1 otherwise (including a strict-mode
    divergence, which aborts the re-drive at that point)."""
    try:
        session = replay_module.load(
            run_id, mode=mode, endpoint=endpoint, api_key=api_key, cache_dir=cache_dir
        )
    except BundleFetchError as exc:
        print(f"trazo replay: {exc}", file=sys.stderr)
        return 1

    report: ReplayReport | None
    divergence: ReplayDivergence | None
    try:
        report = session.run_to(step_index=step)
        divergence = None
    except replay_module.NoEntrypointRegisteredError as exc:
        print(f"trazo replay: {exc}", file=sys.stderr)
        return 1
    except ReplayDivergence as exc:
        report = None
        divergence = exc

    if divergence is not None:
        # Strict mode raised before run_to() could return a report — the
        # Substituter it built is gone with the stack, so report just
        # this one divergence (the one that stopped the re-drive).
        summary = {
            "boundary_fidelity": 0.0,
            "state_fidelity": 0.0,
            "matched": 0,
            "reordered": 0,
            "divergences": [_divergence_summary(divergence)],
        }
        if as_json:
            print(json_module.dumps(summary, indent=2), file=out)
        else:
            _print_report(
                summary,
                run_id=run_id,
                framework=session.bundle.framework,
                mode=mode,
                out=out,
            )
        return 1

    assert report is not None
    summary = _report_summary(report)
    if as_json:
        print(json_module.dumps(summary, indent=2), file=out)
    else:
        _print_report(
            summary,
            run_id=run_id,
            framework=session.bundle.framework,
            mode=mode,
            out=out,
        )
    return 0 if not report.divergences else 1


def _original_duration_ms(bundle: ReplayBundle) -> float | None:
    run_finished = bundle.events_by_kind("run.finished")
    if not run_finished:
        return None
    totals = run_finished[0].payload.get("totals", {})
    duration = totals.get("duration_ms")
    return float(duration) if duration is not None else None


def run_verify(
    run_id: str,
    *,
    endpoint: str,
    api_key: str | None = None,
    cache_dir: Path = _DEFAULT_CACHE_DIR,
    out: TextIO = sys.stdout,
    as_json: bool = False,
) -> int:
    """Fidelity report: boundary fidelity, state fidelity, replay overhead
    (REPLAY_ENGINE.md §5). Always re-drives leniently internally — a
    verification run needs the full picture even when something no
    longer matches, not just the first place it broke."""
    try:
        session = replay_module.load(
            run_id,
            mode="lenient",
            endpoint=endpoint,
            api_key=api_key,
            cache_dir=cache_dir,
        )
    except BundleFetchError as exc:
        print(f"trazo verify: {exc}", file=sys.stderr)
        return 1

    try:
        start = time.monotonic()
        report = session.run_to()
        replay_duration_ms = (time.monotonic() - start) * 1000
    except replay_module.NoEntrypointRegisteredError as exc:
        print(f"trazo verify: {exc}", file=sys.stderr)
        return 1

    original_duration_ms = _original_duration_ms(session.bundle)
    overhead = (
        replay_duration_ms / original_duration_ms if original_duration_ms else None
    )

    summary = _report_summary(report)
    summary["replay_overhead"] = overhead

    if as_json:
        print(json_module.dumps(summary, indent=2), file=out)
    else:
        _print_report(
            summary,
            run_id=run_id,
            framework=session.bundle.framework,
            mode="lenient (verify)",
            out=out,
        )
        overhead_str = f"{overhead:.2f}x" if overhead is not None else "unknown"
        print(f"  replay overhead:   {overhead_str}", file=out)

    return 0 if not report.divergences else 1
