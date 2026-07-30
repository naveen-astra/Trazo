#!/usr/bin/env python3
"""Release-readiness check (TRZ-P7-02): the tag being released must match
every package's own declared version exactly — a wheel/bundle built from
mismatched versions is the kind of mistake that's invisible until someone
downstream tries to correlate a GitHub Release with what's actually
inside it.

Usage: check_release_versions.py <tag> <sdk_pyproject.toml>
    <control_plane_pyproject.toml> <dashboard_package.json>

``tag`` is the git ref name (e.g. ``v0.1.0`` or ``0.1.0`` — the leading
``v`` is stripped if present). Exit 0 if every package's version equals
the tag; exit 1 and print every mismatch otherwise (not just the first,
so a release isn't fixed one round-trip at a time).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_VERSION_RE = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)


def _pyproject_version(path: Path) -> str:
    match = _VERSION_RE.search(path.read_text(encoding="utf-8"))
    if match is None:
        raise ValueError(f"no version field found in {path}")
    return match.group(1)


def _package_json_version(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    version: str = data["version"]
    return version


def check(
    tag: str, *, sdk_version: str, control_plane_version: str, dashboard_version: str
) -> list[str]:
    """Return every version mismatch against ``tag``; empty if none."""
    expected = tag.removeprefix("v")
    violations = []
    for name, actual in (
        ("sdk/pyproject.toml", sdk_version),
        ("control-plane/pyproject.toml", control_plane_version),
        ("dashboard/package.json", dashboard_version),
    ):
        if actual != expected:
            violations.append(f"{name}: version {actual!r} != tag {expected!r}")
    return violations


def main(argv: list[str]) -> int:
    if len(argv) != 5:
        print(
            f"usage: {argv[0]} <tag> <sdk_pyproject.toml> "
            "<control_plane_pyproject.toml> <dashboard_package.json>",
            file=sys.stderr,
        )
        return 2

    tag, sdk_path, control_plane_path, dashboard_path = argv[1:5]
    violations = check(
        tag,
        sdk_version=_pyproject_version(Path(sdk_path)),
        control_plane_version=_pyproject_version(Path(control_plane_path)),
        dashboard_version=_package_json_version(Path(dashboard_path)),
    )
    if violations:
        print("Release version mismatch:", file=sys.stderr)
        for violation in violations:
            print(f"  - {violation}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
