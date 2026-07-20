#!/usr/bin/env python3
"""CI check (TRZ-P1-09): once schema/trace-event.v1.schema.json is frozen,
any change to it must bump ``x-trazo-schema-version`` — silently drifting a
frozen contract is the single most expensive mistake this repo can make
(MASTER_PLAN.md philosophy #1: "the event schema is the product").

Usage: check_schema_version_bump.py <before.json> <after.json>

Exit 0 if the schema is unchanged, or changed together with its version
field; exit 1 if it changed without a version bump. A missing/unparseable
``before`` (e.g. schema didn't exist yet, or this is the freeze commit
itself) is treated as "nothing to compare" — never a violation.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

VERSION_KEY = "x-trazo-schema-version"


def check(before: dict[str, Any], after: dict[str, Any]) -> str | None:
    """Return a violation message, or None if this diff is acceptable."""
    if before == after:
        return None
    if before.get(VERSION_KEY) == after.get(VERSION_KEY):
        return (
            "schema/trace-event.v1.schema.json changed but "
            f"{VERSION_KEY} is still {after.get(VERSION_KEY)!r} — bump it "
            "(and note the change in schema/README.md + CHANGELOG.md), or "
            "revert the schema change."
        )
    return None


def _load(path: Path) -> dict[str, Any]:
    try:
        return dict(json.loads(path.read_text()))
    except (OSError, json.JSONDecodeError):
        return {}


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(f"usage: {argv[0]} <before.json> <after.json>", file=sys.stderr)
        return 2

    before = _load(Path(argv[1]))
    after = _load(Path(argv[2]))
    violation = check(before, after)
    if violation:
        print(violation, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
