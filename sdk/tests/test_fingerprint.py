"""Golden-file + property tests for trazo.core.fingerprint (TRZ-P2-02).

Golden tests pin exact canonical-JSON byte strings (not just "whatever the
code produces") so a future refactor that silently changes ordering, NFC
normalization, or float formatting is caught immediately — this is the
single shared implementation record and replay both depend on
(AGENTS.md); drift here is a silent replay-corruption bug, not a cosmetic
diff.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata

import pytest
from hypothesis import given
from hypothesis import strategies as st

from trazo.core.fingerprint import (
    canonical_json,
    fingerprint_bytes,
    fingerprint_for,
    normalized_inputs,
)

# ---- golden: canonical JSON shape ----


def test_canonical_json__sorts_keys() -> None:
    assert canonical_json({"b": 1, "a": 2}) == b'{"a":2,"b":1}'


def test_canonical_json__no_whitespace() -> None:
    assert canonical_json({"a": [1, 2, 3]}) == b'{"a":[1,2,3]}'


def test_canonical_json__floats_via_repr_shortest() -> None:
    assert canonical_json({"x": 1.0}) == b'{"x":1.0}'
    assert canonical_json({"x": 0.1}) == b'{"x":0.1}'
    assert canonical_json({"x": 100.0}) == b'{"x":100.0}'


def test_canonical_json__strings_normalized_to_nfc() -> None:
    # Built via chr() (never a literal accented character in source, to
    # avoid any ambiguity about which normalization form got typed).
    composed = chr(0xE9)  # U+00E9 LATIN SMALL LETTER E WITH ACUTE (NFC)
    decomposed = "e" + chr(0x0301)  # "e" + COMBINING ACUTE ACCENT (NFD)
    assert composed != decomposed
    assert len(composed) == 1
    assert len(decomposed) == 2
    assert unicodedata.normalize("NFC", decomposed) == composed

    assert canonical_json({"name": decomposed}) == canonical_json({"name": composed})
    expected = ('{"name":"' + composed + '"}').encode("utf-8")
    assert canonical_json({"name": decomposed}) == expected


def test_canonical_json__nested_structures() -> None:
    value = {"z": [{"y": 1}, {"x": 2}], "a": None, "b": True}
    assert canonical_json(value) == b'{"a":null,"b":true,"z":[{"y":1},{"x":2}]}'


# ---- golden: sha256 fingerprint, independently recomputed ----


def test_fingerprint_bytes__matches_independently_computed_sha256() -> None:
    value = {"tool_name": "web_search", "args": {"query": "hi"}}
    expected_canonical = b'{"args":{"query":"hi"},"tool_name":"web_search"}'

    assert canonical_json(value) == expected_canonical
    expected_hash = hashlib.sha256(expected_canonical).hexdigest()
    assert fingerprint_bytes(value) == f"sha256:{expected_hash}"


# ---- golden: per-kind normalized_inputs ----


def test_normalized_inputs__llm_call_excludes_seed_and_response() -> None:
    payload = {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "params": {"temperature": 0.2, "seed": 42},
        "messages_in": [{"role": "user", "content": "hi"}],
        "response": {"role": "assistant", "content": "should not affect fingerprint"},
        "tokens_in": 10,
        "tokens_out": 5,
        "cost_usd": 0.001,
        "latency_ms": 100,
    }
    result = normalized_inputs("llm.call", payload)
    assert result == [
        "openai",
        "gpt-4o-mini",
        {"temperature": 0.2},
        [{"role": "user", "content": "hi"}],
    ]
    # confirm the seed genuinely doesn't affect the fingerprint
    with_different_seed = {**payload, "params": {"temperature": 0.2, "seed": 999}}
    assert fingerprint_for("llm.call", payload) == fingerprint_for(
        "llm.call", with_different_seed
    )


def test_normalized_inputs__tool_call() -> None:
    payload = {"tool_name": "web_search", "args": {"q": "x"}, "result": "ignored"}
    assert normalized_inputs("tool.call", payload) == ["web_search", {"q": "x"}]


def test_normalized_inputs__memory_read() -> None:
    payload = {"store": "vector", "query": "q", "k": 5, "results": "ignored"}
    assert normalized_inputs("memory.read", payload) == ["vector", "q", 5]


def test_normalized_inputs__memory_write() -> None:
    payload = {"store": "vector", "key_or_ns": "ns/1", "value": {"a": 1}}
    assert normalized_inputs("memory.write", payload) == ["vector", "ns/1", {"a": 1}]


def test_normalized_inputs__human_checkpoint_excludes_response() -> None:
    payload = {"prompt": "approve?", "response": "yes", "latency_ms": 500}
    assert normalized_inputs("human.checkpoint", payload) == ["approve?"]


def test_normalized_inputs__unfingerprinted_kind_raises() -> None:
    with pytest.raises(ValueError, match="not a fingerprinted boundary kind"):
        normalized_inputs("run.started", {})


# ---- properties: stability under dict ordering / unicode forms ----


@given(
    st.dictionaries(
        st.text(min_size=1, max_size=5), st.integers() | st.text(max_size=5)
    )
)
def test_property__canonical_json_is_invariant_to_key_insertion_order(
    d: dict[str, object],
) -> None:
    reordered = dict(reversed(list(d.items())))
    assert canonical_json(d) == canonical_json(reordered)


@given(st.text())
def test_property__canonical_json_is_invariant_to_input_unicode_form(s: str) -> None:
    nfc_value = {"k": unicodedata.normalize("NFC", s)}
    nfd_value = {"k": unicodedata.normalize("NFD", s)}
    assert canonical_json(nfc_value) == canonical_json(nfd_value)


@given(
    st.recursive(
        st.none()
        | st.booleans()
        | st.integers()
        | st.floats(allow_nan=False, allow_infinity=False)
        | st.text(max_size=5),
        lambda children: (
            st.lists(children, max_size=3)
            | st.dictionaries(st.text(max_size=5), children, max_size=3)
        ),
        max_leaves=10,
    )
)
def test_property__fingerprint_is_deterministic(value: object) -> None:
    assert fingerprint_bytes(value) == fingerprint_bytes(value)


@given(st.text(max_size=20))
def test_property__canonical_json_round_trips_through_json_loads(s: str) -> None:
    value = {"s": s}
    round_tripped = json.loads(canonical_json(value))
    assert round_tripped["s"] == unicodedata.normalize("NFC", s)
