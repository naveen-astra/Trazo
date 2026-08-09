"""Unit tests for trazo.cli.main (TRZ-P2-08)."""

from __future__ import annotations

import pytest

from trazo.cli.main import _build_parser, main


def test_build_parser__requires_a_subcommand() -> None:
    parser = _build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_build_parser__tail_requires_run_id() -> None:
    parser = _build_parser()

    args = parser.parse_args(["tail", "run_123"])

    assert args.command == "tail"
    assert args.run_id == "run_123"


def test_build_parser__doctor_takes_no_positional_args() -> None:
    parser = _build_parser()

    args = parser.parse_args(["doctor"])

    assert args.command == "doctor"


def test_build_parser__endpoint_defaults_and_is_overridable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TRAZO_ENDPOINT", raising=False)
    parser = _build_parser()

    args = parser.parse_args(["doctor"])
    assert args.endpoint == "http://localhost:8420"

    args = parser.parse_args(["--endpoint", "http://custom:1", "doctor"])
    assert args.endpoint == "http://custom:1"


def test_main__doctor_dispatches_to_run_doctor(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, str] = {}

    def fake_run_doctor(*, endpoint: str) -> int:
        called["endpoint"] = endpoint
        return 0

    monkeypatch.setattr("trazo.cli.main.run_doctor", fake_run_doctor)

    exit_code = main(["--endpoint", "http://example.test", "doctor"])

    assert exit_code == 0
    assert called["endpoint"] == "http://example.test"


def test_main__tail_dispatches_to_tail_run(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, str] = {}

    def fake_tail_run(run_id: str, *, endpoint: str) -> int:
        called["run_id"] = run_id
        called["endpoint"] = endpoint
        return 0

    monkeypatch.setattr("trazo.cli.main.tail_run", fake_tail_run)

    exit_code = main(["tail", "run_1"])

    assert exit_code == 0
    assert called == {"run_id": "run_1", "endpoint": "http://localhost:8420"}


def test_build_parser__replay_defaults_mode_strict_and_no_step() -> None:
    parser = _build_parser()

    args = parser.parse_args(["replay", "run_1"])

    assert args.command == "replay"
    assert args.run_id == "run_1"
    assert args.mode == "strict"
    assert args.step is None
    assert args.as_json is False


def test_build_parser__replay_accepts_step_mode_and_json() -> None:
    parser = _build_parser()

    args = parser.parse_args(
        ["replay", "run_1", "--step", "3", "--mode", "lenient", "--json"]
    )

    assert args.step == 3
    assert args.mode == "lenient"
    assert args.as_json is True


def test_build_parser__replay_rejects_an_invalid_mode() -> None:
    parser = _build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["replay", "run_1", "--mode", "yolo"])


def test_build_parser__verify_requires_run_id() -> None:
    parser = _build_parser()

    args = parser.parse_args(["verify", "run_1"])

    assert args.command == "verify"
    assert args.run_id == "run_1"
    assert args.as_json is False
    assert args.submit is True  # submits by default


def test_build_parser__verify_no_submit_flag() -> None:
    parser = _build_parser()

    args = parser.parse_args(["verify", "run_1", "--no-submit"])

    assert args.submit is False


def test_main__replay_dispatches_to_run_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, object] = {}

    def fake_run_replay(run_id: str, **kwargs: object) -> int:
        called["run_id"] = run_id
        called.update(kwargs)
        return 0

    monkeypatch.setattr("trazo.cli.main.run_replay", fake_run_replay)

    exit_code = main(["replay", "run_1", "--mode", "lenient"])

    assert exit_code == 0
    assert called["run_id"] == "run_1"
    assert called["mode"] == "lenient"
    assert called["endpoint"] == "http://localhost:8420"


def test_main__verify_dispatches_to_run_verify(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, object] = {}

    def fake_run_verify(run_id: str, **kwargs: object) -> int:
        called["run_id"] = run_id
        called.update(kwargs)
        return 0

    monkeypatch.setattr("trazo.cli.main.run_verify", fake_run_verify)

    exit_code = main(["verify", "run_1", "--json"])

    assert exit_code == 0
    assert called["run_id"] == "run_1"
    assert called["as_json"] is True
    assert called["submit"] is True


def test_main__verify_no_submit_dispatches_submit_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: dict[str, object] = {}

    def fake_run_verify(run_id: str, **kwargs: object) -> int:
        called["run_id"] = run_id
        called.update(kwargs)
        return 0

    monkeypatch.setattr("trazo.cli.main.run_verify", fake_run_verify)

    exit_code = main(["verify", "run_1", "--no-submit"])

    assert exit_code == 0
    assert called["submit"] is False


def test_main__tail_keyboard_interrupt_returns_130(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_tail_run(run_id: str, *, endpoint: str) -> int:
        raise KeyboardInterrupt

    monkeypatch.setattr("trazo.cli.main.tail_run", fake_tail_run)

    exit_code = main(["tail", "run_1"])

    assert exit_code == 130
