"""Unit tests for trazo.integrations.langgraph.state_serializer (TRZ-P2-04)."""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from trazo.integrations.langgraph.state_serializer import hash_state, serialize_state


def test_serialize_state__plain_json_native_state_has_no_unhashed_keys() -> None:
    snapshot, unhashed = serialize_state({"count": 1, "log": ["a", "b"], "ok": True})

    assert snapshot == {"count": 1, "log": ["a", "b"], "ok": True}
    assert unhashed == []


def test_serialize_state__langchain_message_is_serialized_via_model_dump() -> None:
    snapshot, unhashed = serialize_state({"messages": [HumanMessage(content="hi")]})

    assert unhashed == []
    assert snapshot["messages"][0]["content"] == "hi"
    assert snapshot["messages"][0]["type"] == "human"


class _Unrepresentable:
    def __repr__(self) -> str:
        return "<Unrepresentable object>"


def test_serialize_state__unrepresentable_value_is_marked_and_excluded_from_hash() -> (
    None
):
    snapshot, unhashed = serialize_state({"weird": _Unrepresentable(), "ok": 1})

    assert unhashed == ["weird"]
    assert snapshot["weird"] == {"$unrepresentable": "<Unrepresentable object>"}
    assert snapshot["ok"] == 1


def test_hash_state__excludes_unhashed_keys_from_the_hash_input() -> None:
    """Two states differing only in an unrepresentable field's identity
    must hash identically — the whole point of excluding it."""

    class _A:
        def __repr__(self) -> str:
            return "a"

    class _B:
        def __repr__(self) -> str:
            return "b"

    hash_a, _snapshot_a, unhashed_a = hash_state({"ok": 1, "weird": _A()})
    hash_b, _snapshot_b, unhashed_b = hash_state({"ok": 1, "weird": _B()})

    assert unhashed_a == unhashed_b == ["weird"]
    assert hash_a == hash_b


def test_hash_state__different_hashable_content_produces_different_hashes() -> None:
    hash_1, _, _ = hash_state({"count": 1})
    hash_2, _, _ = hash_state({"count": 2})

    assert hash_1 != hash_2
    assert hash_1.startswith("sha256:")
