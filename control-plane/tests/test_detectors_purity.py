"""Enforces AI_DEBUGGER.md §2's "pure functions... no I/O, no store
access" rule for every module under ``trazo_server.detectors`` (TRZ-P5-03
's "pure-function contract enforced by lint rule" DoD): an AST scan, not
a runtime check, so a detector doesn't even need to be *called* for a
banned import to fail CI — a bad `import` alone is enough to break this
test, before it ever gets a chance to do any I/O.
"""

from __future__ import annotations

import ast
from pathlib import Path

_DETECTORS_PKG = (
    Path(__file__).resolve().parents[1] / "src" / "trazo_server" / "detectors"
)

# Prefixes that indicate I/O, network, or store access — anything a
# detector reaching for would break "derivable from the stream alone"
# (and so break offline benchmarking against a recorded stream with no
# bus/store at all, benchmark/detection/runner.py).
_BANNED_IMPORT_PREFIXES = (
    "httpx",
    "requests",
    "aiohttp",
    "redis",
    "asyncpg",
    "sqlalchemy",
    "psycopg",
    "boto3",
    "socket",
    "trazo_server.bus",
    "trazo_server.store",
    "trazo_server.workers",
)


def _imported_names(tree: ast.Module) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.append(node.module)
    return names


def _banned_imports_in(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        name
        for name in _imported_names(tree)
        if any(
            name == prefix or name.startswith(prefix + ".")
            for prefix in _BANNED_IMPORT_PREFIXES
        )
    ]


def test_detectors_package_exists_and_has_modules_to_check() -> None:
    """Guards against this test silently passing if the package ever gets
    renamed/moved and the glob below starts matching nothing."""
    assert _DETECTORS_PKG.is_dir()
    modules = list(_DETECTORS_PKG.glob("*.py"))
    assert modules, f"no .py files found under {_DETECTORS_PKG}"


def test_no_detector_module_imports_io_or_store_access() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _DETECTORS_PKG.glob("*.py"):
        banned = _banned_imports_in(path)
        if banned:
            offenders[path.name] = banned

    assert not offenders, (
        "detectors must be pure functions of (event, window) — no I/O, no "
        f"store access (AI_DEBUGGER.md §2); found banned imports: {offenders}"
    )
