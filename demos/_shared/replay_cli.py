"""The command line every demo's ``replay_entrypoint.py`` shares.

    replay_entrypoint.py <run_id> [--mode verify|strict|lenient] [--step N]
        [--endpoint http://localhost:8420] [--json]

``verify`` (the default) is ``trazo verify``: a lenient re-drive that
reports boundary fidelity, state fidelity and every divergence, and
submits the report to the control plane for Replay Studio. ``strict`` and
``lenient`` are ``trazo replay``: strict stops at the first divergence,
which is the mode to reach for when bisecting a regression.

Before the demo's own modules load, the run's recorded model labels are
adopted (``adopt_recorded_labels``). A traced call's provider and model
are part of its fingerprint and replay never calls the model, so a run
recorded live against, say, Ollama would otherwise replay with fixture
labels and mismatch on every ``llm.call``.
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Callable

from live_llm import TRACE_MODEL_ENV, TRACE_PROVIDER_ENV

from trazo import replay
from trazo.cli.replay import run_replay, run_verify


def recorded_llm_labels(
    run_id: str, *, endpoint: str, api_key: str | None
) -> tuple[str, str] | None:
    """The provider and model of the run's first ``llm.call``, or ``None``
    for a run that made no model calls. Uses the same cached bundle the
    replay itself then reuses, so this costs one fetch at most. A fetch
    that fails is not reported here: the replay that follows fails the same
    way and reports it properly."""
    try:
        session = replay.load(
            run_id, mode="lenient", endpoint=endpoint, api_key=api_key
        )
    except Exception:
        return None
    for event in session.bundle.events_by_kind("llm.call"):
        provider, model = event.payload.get("provider"), event.payload.get("model")
        if isinstance(provider, str) and isinstance(model, str):
            return provider, model
    return None


def adopt_recorded_labels(
    run_id: str, *, endpoint: str, api_key: str | None
) -> tuple[str, str] | None:
    """Label this process's traced calls the way the recorded run's were.
    Labels already set in the environment win, so they can still be
    forced by hand."""
    if os.environ.get(TRACE_PROVIDER_ENV) and os.environ.get(TRACE_MODEL_ENV):
        return None
    labels = recorded_llm_labels(run_id, endpoint=endpoint, api_key=api_key)
    if labels is not None:
        os.environ[TRACE_PROVIDER_ENV], os.environ[TRACE_MODEL_ENV] = labels
    return labels


def main(*, description: str | None, register: Callable[[], None]) -> int:
    """Parse the shared arguments, adopt the run's labels, then call
    ``register`` -- which imports the demo and registers its
    ``@replay.entrypoint`` -- and re-drive the run."""
    parser = argparse.ArgumentParser(
        description=description, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("run_id")
    parser.add_argument(
        "--mode",
        choices=("verify", "strict", "lenient"),
        default="verify",
        help="verify: fidelity report (default); strict: stop at the first "
        "divergence; lenient: record divergences and carry on",
    )
    parser.add_argument(
        "--step",
        type=int,
        default=None,
        help="strict/lenient only: re-drive up to this step index",
    )
    parser.add_argument(
        "--endpoint", default=os.environ.get("TRAZO_ENDPOINT", "http://localhost:8420")
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    if args.step is not None and args.mode == "verify":
        parser.error("--step needs --mode strict or --mode lenient")

    api_key = os.environ.get("TRAZO_API_KEY")
    adopt_recorded_labels(args.run_id, endpoint=args.endpoint, api_key=api_key)
    register()

    if args.mode == "verify":
        return run_verify(
            args.run_id, endpoint=args.endpoint, api_key=api_key, as_json=args.as_json
        )
    return run_replay(
        args.run_id,
        mode=args.mode,
        step=args.step,
        endpoint=args.endpoint,
        api_key=api_key,
        as_json=args.as_json,
    )
