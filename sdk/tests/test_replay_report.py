"""Unit tests for trazo.core.replay_report (TRZ-P4-03)."""

from __future__ import annotations

from trazo.core.replay_report import DivergenceDetail, ReplayDivergence, ReplayReport


def test_fidelity__is_1_0_with_no_boundary_calls() -> None:
    report = ReplayReport()

    assert report.fidelity == 1.0


def test_fidelity__all_matched_is_1_0() -> None:
    report = ReplayReport()
    report.record_match(
        kind="llm.call",
        fingerprint="sha256:a",
        event_id="evt_1",
        seq=0,
        reordered=False,
    )
    report.record_match(
        kind="tool.call",
        fingerprint="sha256:b",
        event_id="evt_2",
        seq=1,
        reordered=False,
    )

    assert report.fidelity == 1.0


def test_fidelity__reflects_divergence_ratio() -> None:
    report = ReplayReport()
    report.record_match(
        kind="llm.call",
        fingerprint="sha256:a",
        event_id="evt_1",
        seq=0,
        reordered=False,
    )
    divergence = ReplayDivergence(
        "tool.call",
        "mismatch",
        DivergenceDetail(
            expected_seq=1,
            expected_event_id="evt_2",
            expected_fingerprint="sha256:b",
            live_fingerprint="sha256:c",
            live_inputs={},
        ),
    )
    report.record_divergence(divergence)

    assert report.fidelity == 0.5
    assert report.divergences == [divergence]


def test_reordered_count__counts_only_reordered_matches() -> None:
    report = ReplayReport()
    report.record_match(
        kind="llm.call",
        fingerprint="sha256:a",
        event_id="evt_1",
        seq=0,
        reordered=False,
    )
    report.record_match(
        kind="llm.call", fingerprint="sha256:b", event_id="evt_2", seq=1, reordered=True
    )

    assert report.reordered_count == 1


def test_replay_divergence__message_includes_kind_and_fingerprints() -> None:
    divergence = ReplayDivergence(
        "llm.call",
        "exhausted",
        DivergenceDetail(
            expected_seq=None,
            expected_event_id=None,
            expected_fingerprint=None,
            live_fingerprint="sha256:live",
            live_inputs={"provider": "openai"},
        ),
    )

    message = str(divergence)

    assert "llm.call" in message
    assert "exhausted" in message
    assert "sha256:live" in message
