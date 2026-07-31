#!/usr/bin/env python3
"""Debt-tracking check (IMPLEMENTATION_PLAN.md §8, TRZ-P7-05): every debt
marker comment must reference a real task ID (``TRZ-P<phase>-<nn>``) — a
bare marker with no linked issue is exactly the "debt with no repayment
plan" this convention exists to prevent.

Found via ``git grep`` (tracked files only), so generated/vendored trees
(``.venv``, ``node_modules``, ``dist``) never need an explicit exclude
list — this script's own path is the only exclusion, since its source
necessarily contains the marker text it's checking for.

Usage: check_debt_comments.py [repo_root]
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# This file is excluded from its own git-grep scan (_SELF_PATH below) --
# without that, every occurrence of _MARKER's literal text here would be
# flagged as a violation, since none of them are real task-ID references.
_MARKER = "DEBT("
_REF_LINE = re.compile(re.escape(_MARKER) + r"([^)]*)\)")
_VALID_REF = re.compile(r"^TRZ-P\d+-\d+$")
_SELF_PATH = "scripts/check_debt_comments.py"


def find_violations_in_line(path: str, lineno: str, content: str) -> list[str]:
    """Pure, testable core: given one ``git grep -n`` output line already
    split into (path, lineno, content), return every malformed marker
    reference on it."""
    violations = []
    for match in _REF_LINE.finditer(content):
        ref = match.group(1).strip()
        if not _VALID_REF.match(ref):
            violations.append(
                f"{path}:{lineno}: {_MARKER}{ref!r}) does not reference a "
                f"valid task ID (expected {_MARKER}TRZ-P<phase>-<nn>))"
            )
    return violations


def find_violations(repo_root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "grep", "-n", "-I", _MARKER, "--", ".", f":!{_SELF_PATH}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in (0, 1):  # 1 == no matches, not a failure
        raise RuntimeError(f"git grep failed: {result.stderr}")

    violations = []
    for line in result.stdout.splitlines():
        path, _, rest = line.partition(":")
        lineno, _, content = rest.partition(":")
        violations.extend(find_violations_in_line(path, lineno, content))
    return violations


def main(argv: list[str]) -> int:
    repo_root = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parents[1]
    violations = find_violations(repo_root)
    if violations:
        print(f"{_MARKER[:-1]} comment check failed:", file=sys.stderr)
        for violation in violations:
            print(f"  - {violation}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
