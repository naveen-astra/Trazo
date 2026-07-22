"""LangGraph state serialization for step.* hashing (TRZ-P2-04).

Per EVENTS.md §4: ``state_*_hash`` is ``sha256(canonical_json(...))`` of
"the adapter's state_serializer" output, and this adapter documents
exactly what's included/excluded: LangGraph channel values that are JSON-
native or LangChain-message-like (have ``model_dump``) pass through;
anything else is replaced by a ``$unrepresentable`` marker in the
snapshot payload and its key is listed in ``unhashed_keys`` — excluded
from the hash so an opaque object's ``repr()`` (which may not even be
stable) never silently makes replay fidelity impossible to achieve.
"""

from __future__ import annotations

from typing import Any

from trazo.core.fingerprint import fingerprint_bytes


def _try_serialize_value(value: Any) -> tuple[Any, bool]:
    """Returns (json_safe_value, is_native). ``is_native`` False means the
    value had to fall back to a non-reversible representation."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value, True
    if isinstance(value, dict):
        result: dict[Any, Any] = {}
        all_native = True
        for k, v in value.items():
            serialized, native = _try_serialize_value(v)
            result[k] = serialized
            all_native = all_native and native
        return result, all_native
    if isinstance(value, (list, tuple)):
        results = []
        all_native = True
        for item in value:
            serialized, native = _try_serialize_value(item)
            results.append(serialized)
            all_native = all_native and native
        return results, all_native

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return model_dump(mode="json"), True
        except Exception:
            pass
    return {"$unrepresentable": repr(value)}, False


def serialize_state(state: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Returns (json_safe_snapshot, unhashed_keys)."""
    snapshot: dict[str, Any] = {}
    unhashed_keys: list[str] = []
    for key, value in state.items():
        serialized, native = _try_serialize_value(value)
        snapshot[key] = serialized
        if not native:
            unhashed_keys.append(key)
    return snapshot, unhashed_keys


def to_json_safe(value: Any) -> Any:
    """Best-effort JSON-safe conversion for a single value (e.g. an LLM
    response message or a tool's return value) — same fallback rules as
    ``serialize_state``, without the hash-exclusion bookkeeping."""
    serialized, _native = _try_serialize_value(value)
    return serialized


def hash_state(state: dict[str, Any]) -> tuple[str, dict[str, Any], list[str]]:
    """Returns (state_hash, json_safe_snapshot, unhashed_keys). The hash
    covers only keys that serialized natively — EVENTS.md §4's contract."""
    snapshot, unhashed_keys = serialize_state(state)
    hashed_view = {k: v for k, v in snapshot.items() if k not in unhashed_keys}
    state_hash = fingerprint_bytes(hashed_view)
    return state_hash, snapshot, unhashed_keys
