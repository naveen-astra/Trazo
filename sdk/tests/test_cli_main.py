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


def test_main__tail_keyboard_interrupt_returns_130(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_tail_run(run_id: str, *, endpoint: str) -> int:
        raise KeyboardInterrupt

    monkeypatch.setattr("trazo.cli.main.tail_run", fake_tail_run)

    exit_code = main(["tail", "run_1"])

    assert exit_code == 130
