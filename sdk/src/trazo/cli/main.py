"""``trazo`` CLI entry point (TRZ-P2-08): argparse dispatcher for ``tail``
and ``doctor``. Registered as the ``trazo`` console script (pyproject.toml
``[project.scripts]``).
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence

from trazo.cli.doctor import run_doctor
from trazo.cli.tail import tail_run

_DEFAULT_ENDPOINT = "http://localhost:8420"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trazo", description="Trazo SDK command-line tool"
    )
    parser.add_argument(
        "--endpoint",
        default=os.environ.get("TRAZO_ENDPOINT", _DEFAULT_ENDPOINT),
        help=f"control plane base URL (default {_DEFAULT_ENDPOINT})",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    tail_parser = subparsers.add_parser("tail", help="stream one run's events live")
    tail_parser.add_argument("run_id")

    subparsers.add_parser(
        "doctor", help="check connectivity, spool status, version skew"
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "tail":
        try:
            return tail_run(args.run_id, endpoint=args.endpoint)
        except KeyboardInterrupt:
            return 130

    return run_doctor(endpoint=args.endpoint)


if __name__ == "__main__":
    sys.exit(main())
