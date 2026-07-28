"""VCR-style recorded-completions cassette for demo LLM calls (TRZ-P3-04).

A cassette is a flat JSON file mapping a request key (a canonical hash of
the caller's identifying arguments) to a previously-recorded response. It
has exactly two operations, matching how demos actually use it:

- Fixture mode (default, zero API cost): ``get()`` a key; a miss means
  "no real recording exists yet" — callers fall back to a deterministic
  stub rather than treating it as an error, so a demo works today, before
  any cassette has ever been recorded. This is *not* a strict VCR ("missing
  cassette is a test failure") because these demos shipped with a
  deterministic fixture path before this task existed (TRZ-P3-02/03); the
  cassette is an additive upgrade over that baseline, not a replacement it
  depends on.
- Live mode (opt-in, needs a real API key): every response ``put()`` is
  recorded, so a `--live` run both generates a fresh corpus entry
  (TRZ-P3-05) *and* refreshes the fixture cassette for the next CI run —
  the two clauses in TRZ-P3-04's title share one mechanism, not two.

Not part of the SDK's public surface: IMPLEMENTATION_PLAN.md's lane table
scopes `demos/` to the SDK's public API for tracing, but this module
doesn't trace anything — it's demo-local test infrastructure, same lane
(D) as the demos that use it.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def request_key(name: str, kwargs: dict[str, Any]) -> str:
    """A stable hash identifying one call, independent of dict key order.

    ``name`` disambiguates functions/tags that might otherwise share an
    argument shape (e.g. two ``ask_*`` functions that both take a single
    ``str``).
    """
    canonical = json.dumps(
        {"name": name, "kwargs": kwargs}, sort_keys=True, default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


class Cassette:
    """A JSON-backed key -> recorded-response store for one demo.

    Loads eagerly on construction and only writes on ``save()`` — callers
    control exactly when a recording hits disk (typically: immediately
    after each live call, so a run killed partway through still keeps
    whatever it recorded so far).
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._entries: dict[str, dict[str, Any]] = {}
        if path.exists():
            self._entries = json.loads(path.read_text(encoding="utf-8"))

    def get(self, key: str) -> dict[str, Any] | None:
        return self._entries.get(key)

    def put(self, key: str, response: dict[str, Any]) -> None:
        self._entries[key] = response

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._entries, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )

    def __len__(self) -> int:
        return len(self._entries)
