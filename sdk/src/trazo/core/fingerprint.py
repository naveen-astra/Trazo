"""Canonical JSON + per-kind fingerprint normalization (TRZ-P2-02).

**The single shared implementation for record and replay** (AGENTS.md hard
rule: "One fingerprint implementation... Never reimplement normalization
anywhere else"). REPLAY_ENGINE.md's replay cursor-matching depends on the
live fingerprint and the recorded fingerprint being byte-identical for the
same logical input — any drift here silently corrupts replay matching.

EVENTS.md §3 gives the normalized-inputs formula for three kinds
(``llm.call``, ``tool.call``, ``memory.read``) explicitly. Read together,
§2.3 ("the replay-critical four": llm.call/tool.call/memory.read/
memory.write) and §2.4 (human.checkpoint "treated as a boundary
(fingerprinted)") imply a fifth and sixth normalization rule this module
had to infer rather than transcribe — flagged below, and exactly the kind
of judgment call this task's DoD calls for A+B review on:

- ``memory.write``: normalized on ``(store, key_or_ns, value)`` — the
  write's identity, analogous to memory.read's ``(store, query, k)``.
- ``human.checkpoint``: normalized on ``(prompt,)`` only — the prompt is
  the "input"; the human's ``response`` is the non-deterministic result
  being substituted on replay, so it's excluded the same way an llm.call's
  ``response`` is excluded from its own fingerprint.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any

JsonValue = Any  # recursive structure; Any is the honest bound here

# EVENTS.md §2.3-2.4: exactly these five kinds carry a fingerprint.
FINGERPRINTED_KINDS = frozenset(
    {"llm.call", "tool.call", "memory.read", "memory.write", "human.checkpoint"}
)


def _normalize(value: JsonValue) -> JsonValue:
    """Recursively NFC-normalize every string (key or value)."""
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, dict):
        return {_normalize(k): _normalize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize(v) for v in value]
    return value


def canonical_json(value: JsonValue) -> bytes:
    """EVENTS.md §3 canonical JSON: sorted keys, no whitespace, NFC
    strings, floats via repr-shortest.

    ``json.dumps`` already renders floats via ``float.__repr__``, which has
    been the shortest round-trippable representation since Python 3.1 —
    no custom float formatting needed as long as this stays the only
    serialization path.
    """
    normalized = _normalize(value)
    return json.dumps(
        normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def fingerprint_bytes(value: JsonValue) -> str:
    """``sha256:<hex>`` of the canonical JSON of an already-normalized value."""
    digest = hashlib.sha256(canonical_json(value)).hexdigest()
    return f"sha256:{digest}"


def normalized_inputs(kind: str, payload: dict[str, Any]) -> JsonValue:
    """Extract the kind-specific tuple that gets fingerprinted (EVENTS.md §3).

    Raises ValueError for any kind outside FINGERPRINTED_KINDS.
    """
    if kind == "llm.call":
        params = {k: v for k, v in payload["params"].items() if k != "seed"}
        return [payload["provider"], payload["model"], params, payload["messages_in"]]
    if kind == "tool.call":
        return [payload["tool_name"], payload["args"]]
    if kind == "memory.read":
        return [payload["store"], payload["query"], payload["k"]]
    if kind == "memory.write":
        return [payload["store"], payload["key_or_ns"], payload["value"]]
    if kind == "human.checkpoint":
        return [payload["prompt"]]
    raise ValueError(f"{kind!r} is not a fingerprinted boundary kind")


def fingerprint_for(kind: str, payload: dict[str, Any]) -> str:
    """The ``fingerprint`` value to put on an envelope of this kind."""
    return fingerprint_bytes(normalized_inputs(kind, payload))
