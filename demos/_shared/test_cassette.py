"""Unit tests for the recorded-completions cassette (TRZ-P3-04)."""

from __future__ import annotations

from pathlib import Path

from cassette import Cassette, request_key


def test_request_key__stable_regardless_of_kwargs_order() -> None:
    a = request_key("ask_plan", {"question": "x", "queries_done": ["a"]})
    b = request_key("ask_plan", {"queries_done": ["a"], "question": "x"})
    assert a == b


def test_request_key__differs_by_function_name_for_identical_args() -> None:
    a = request_key("ask_plan", {"x": 1})
    b = request_key("ask_evaluate", {"x": 1})
    assert a != b


def test_request_key__differs_by_argument_value() -> None:
    a = request_key("ask_plan", {"question": "x"})
    b = request_key("ask_plan", {"question": "y"})
    assert a != b


def test_cassette__miss_on_empty_cassette(tmp_path: Path) -> None:
    cassette = Cassette(tmp_path / "cassette.json")
    assert cassette.get("nonexistent") is None
    assert len(cassette) == 0


def test_cassette__put_then_get_round_trips(tmp_path: Path) -> None:
    cassette = Cassette(tmp_path / "cassette.json")
    key = request_key("ask_plan", {"question": "hi"})
    cassette.put(key, {"response": "hello", "tokens_in": 1, "tokens_out": 1})

    assert cassette.get(key) == {"response": "hello", "tokens_in": 1, "tokens_out": 1}


def test_cassette__save_then_load_from_a_fresh_instance_recovers_all_entries(
    tmp_path: Path,
) -> None:
    path = tmp_path / "cassette.json"
    original = Cassette(path)
    key = request_key("ask_finalize", {"question": "hi", "findings": ["a", "b"]})
    original.put(key, {"response": "final answer", "tokens_in": 5, "tokens_out": 2})
    original.save()

    reloaded = Cassette(path)
    assert reloaded.get(key) == {
        "response": "final answer",
        "tokens_in": 5,
        "tokens_out": 2,
    }
    assert len(reloaded) == 1


def test_cassette__save_creates_parent_directories(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "dir" / "cassette.json"
    cassette = Cassette(path)
    cassette.put("k", {"response": "v", "tokens_in": 1, "tokens_out": 1})
    cassette.save()

    assert path.exists()
    assert Cassette(path).get("k") == {"response": "v", "tokens_in": 1, "tokens_out": 1}
