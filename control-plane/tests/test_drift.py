"""Unit tests for trazo_server.drift (the opt-in goal-drift judge) and its
place in the detector worker. No model is contacted: the judge is driven
through an httpx mock transport or replaced by a scripted fake."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from trazo_server.bus.memory import InMemoryEventBus
from trazo_server.config import Settings
from trazo_server.detectors.base import Detection, LlmExchange, RunWindow, excerpt
from trazo_server.drift import (
    DriftDetector,
    DriftJudge,
    DriftVerdict,
    build_drift_detector,
    build_prompt,
    parse_verdict,
)
from trazo_server.events import Event, EventAdapter
from trazo_server.store.memory_trace_store import InMemoryTraceStore
from trazo_server.topics import EVENTS_STREAM
from trazo_server.workers.detector_worker import DetectorWorker

_RUN_ID = "run_1"


def _event(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "schema": "trazo.v1",
        "event_id": "evt_start",
        "run_id": _RUN_ID,
        "project": "proj",
        "seq": 0,
        "ts": "2026-07-18T09:30:00.000Z",
        "kind": "run.started",
        "payload": {
            "framework": "langgraph",
            "framework_version": "0.2.39",
            "sdk_version": "0.1.0",
            "entry_input": {"question": "what is trazo"},
            "tags": {},
        },
    }
    base.update(overrides)
    return base


def _run_started(entry_input: Any = None, run_id: str = _RUN_ID) -> Event:
    payload = _event()["payload"]
    if entry_input is not None:
        payload["entry_input"] = entry_input
    return EventAdapter.validate_python(
        _event(payload=payload, run_id=run_id, event_id=f"evt_start_{run_id}")
    )


def _llm_call(seq: int, *, run_id: str = _RUN_ID, response: str = "ok") -> Event:
    return EventAdapter.validate_python(
        _event(
            event_id=f"evt_llm_{run_id}_{seq}",
            run_id=run_id,
            seq=seq,
            kind="llm.call",
            fingerprint=f"sha256:{'a' * 64}",
            payload={
                "provider": "fixture",
                "model": "fixture-v1",
                "params": {},
                "messages_in": {"question": "what is trazo", "n": seq},
                "response": response,
                "tokens_in": 1,
                "tokens_out": 1,
                "cost_usd": 0.0,
                "latency_ms": 1.0,
            },
        )
    )


class _ScriptedJudge:
    """Stands in for DriftJudge: returns verdicts from a script and
    remembers what it was asked."""

    model = "scripted"

    def __init__(self, verdicts: list[DriftVerdict | None]) -> None:
        self._verdicts = list(verdicts)
        self.calls: list[tuple[str | None, list[LlmExchange]]] = []

    def judge(
        self, goal: str | None, exchanges: list[LlmExchange]
    ) -> DriftVerdict | None:
        self.calls.append((goal, list(exchanges)))
        return self._verdicts.pop(0) if self._verdicts else DriftVerdict(True, "")


_ON = DriftVerdict(on_task=True, reason="fine")
_OFF = DriftVerdict(on_task=False, reason="houseplants")


def _drive(
    detector: DriftDetector, window: RunWindow, events: list[Event]
) -> list[Detection]:
    found = []
    for event in events:
        window.record(event)
        detection = detector.evaluate(event, window)
        if detection is not None:
            found.append(detection)
    return found


# --- parse_verdict ---


@pytest.mark.parametrize(
    ("text", "on_task"),
    [
        ('{"reason": "fine", "drifted": false}', True),
        ('{"reason": "houseplants", "drifted": true}', False),
        ('Sure! ```json\n{"reason": "x", "drifted": true}\n```', False),
        ('thinking... {"not": "it"} {"reason": "y", "drifted": false}', True),
    ],
)
def test_parse_verdict__reads_the_drifted_flag(text: str, on_task: bool) -> None:
    verdict = parse_verdict(text)

    assert verdict is not None
    assert verdict.on_task is on_task


@pytest.mark.parametrize(
    "text",
    ["", "no json here", '{"drifted": "yes"}', '{"reason": "no flag"}', "{broken"],
)
def test_parse_verdict__anything_else_is_no_verdict(text: str) -> None:
    assert parse_verdict(text) is None


def test_parse_verdict__a_long_reason_is_cut() -> None:
    verdict = parse_verdict(json.dumps({"reason": "x" * 1000, "drifted": False}))

    assert verdict is not None
    assert len(verdict.reason) == 300


# --- prompts ---


def test_build_prompt__goal_mode_states_the_goal_and_numbers_exchanges() -> None:
    prompt = build_prompt(
        "what is trazo",
        [
            LlmExchange("e1", "in one", "out one"),
            LlmExchange("e2", "in two", "out two"),
        ],
    )

    assert prompt.startswith("GOAL:\nwhat is trazo")
    assert "[1] INPUT: in one" in prompt
    assert "[2] OUTPUT: out two" in prompt


def test_build_prompt__task_mode_has_no_goal_section() -> None:
    prompt = build_prompt(None, [LlmExchange("e1", "in", "out")])

    assert "GOAL" not in prompt
    assert "[1] INPUT: in" in prompt


def test_excerpt__keeps_the_start_and_the_end_of_a_long_value() -> None:
    long_value = "START" + "x" * 5000 + "END"

    text = excerpt(long_value)

    assert text.startswith("START")
    assert text.endswith("END")
    assert len(text) < 900


# --- DriftJudge over HTTP ---


def _judge_with(handler: Any) -> DriftJudge:
    return DriftJudge(
        base_url="http://judge.test/v1/",
        model="m",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def _reply(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def test_drift_judge__sends_a_deterministic_chat_request_and_parses_the_reply() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _reply('{"reason": "off", "drifted": true}')

    verdict = _judge_with(handler).judge("goal", [LlmExchange("e", "in", "out")])

    assert verdict == DriftVerdict(on_task=False, reason="off")
    request = seen[0]
    assert str(request.url) == "http://judge.test/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer unused"
    body = json.loads(request.content)
    assert body["temperature"] == 0
    assert body["model"] == "m"
    messages = body["messages"]
    assert messages[0]["role"] == "system"
    assert "goal drift" in messages[0]["content"]
    # Worked examples sit between the instructions and the real question, as
    # alternating user/assistant turns whose answers are in the JSON format.
    examples = messages[1:-1]
    assert examples
    roles = [m["role"] for m in examples]
    assert roles == ["user", "assistant"] * (len(examples) // 2)
    assert all(parse_verdict(m["content"]) for m in examples[1::2])
    assert messages[-1]["role"] == "user"
    assert "GOAL:\ngoal" in messages[-1]["content"]


def test_drift_judge__uses_the_task_prompt_when_the_run_has_no_goal() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return _reply('{"reason": "ok", "drifted": false}')

    _judge_with(handler).judge(None, [LlmExchange("e", "in", "out")])

    messages = bodies[0]["messages"]
    assert "Different exchanges may be different tasks" in messages[0]["content"]
    assert all("GOAL:" not in m["content"] for m in messages[1:])


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, text="boom"),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, text="not json"),
        _reply("I cannot say"),
    ],
)
def test_drift_judge__a_failing_or_unparseable_judge_is_no_verdict(
    response: httpx.Response,
) -> None:
    judge = _judge_with(lambda request: response)

    assert judge.judge("goal", [LlmExchange("e", "in", "out")]) is None


def test_drift_judge__an_unreachable_server_is_no_verdict() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    assert _judge_with(handler).judge("g", [LlmExchange("e", "i", "o")]) is None


# --- DriftDetector ---


def test_drift__judges_every_nth_model_call_not_every_call() -> None:
    judge = _ScriptedJudge([])
    detector = DriftDetector(judge, every_n_llm_calls=2, min_llm_calls=2)  # type: ignore[arg-type]
    window = RunWindow(_RUN_ID)

    _drive(detector, window, [_run_started(), *[_llm_call(i) for i in range(1, 8)]])

    assert len(judge.calls) == 3  # after the 2nd, 4th and 6th model call


def test_drift__needs_consecutive_off_task_verdicts_and_an_on_task_one_resets() -> None:
    judge = _ScriptedJudge([_OFF, _ON, _OFF, _OFF])
    detector = DriftDetector(
        judge,  # type: ignore[arg-type]
        every_n_llm_calls=1,
        confirmations=2,
        min_llm_calls=1,
    )
    window = RunWindow(_RUN_ID)

    detections = _drive(
        detector, window, [_run_started(), *[_llm_call(i) for i in range(1, 5)]]
    )

    assert len(detections) == 1
    assert detections[0].evidence_event_ids[-1] == f"evt_llm_{_RUN_ID}_4"
    assert detections[0].detector == "drift"
    assert detections[0].severity == "warn"
    assert detections[0].details["reason"] == "houseplants"
    assert detections[0].details["judge_model"] == "scripted"


def test_drift__raises_at_most_once_per_run() -> None:
    judge = _ScriptedJudge([_OFF] * 10)
    detector = DriftDetector(
        judge,  # type: ignore[arg-type]
        every_n_llm_calls=1,
        confirmations=2,
        min_llm_calls=1,
    )
    window = RunWindow(_RUN_ID)

    detections = _drive(
        detector, window, [_run_started(), *[_llm_call(i) for i in range(1, 9)]]
    )

    assert len(detections) == 1
    assert len(judge.calls) == 2  # it stopped asking once it had fired


def test_drift__a_judge_that_fails_neither_fires_nor_resets_the_count() -> None:
    judge = _ScriptedJudge([_OFF, None, _OFF])
    detector = DriftDetector(
        judge,  # type: ignore[arg-type]
        every_n_llm_calls=1,
        confirmations=2,
        min_llm_calls=1,
    )
    window = RunWindow(_RUN_ID)

    detections = _drive(
        detector, window, [_run_started(), *[_llm_call(i) for i in range(1, 4)]]
    )

    assert len(detections) == 1  # off, (no verdict), off -> two off-task in a row


def test_drift__judges_against_the_stated_goal_or_falls_back_to_task_mode() -> None:
    stated = _ScriptedJudge([])
    window = RunWindow(_RUN_ID)
    _drive(
        DriftDetector(stated, every_n_llm_calls=1, min_llm_calls=1),  # type: ignore[arg-type]
        window,
        [_run_started({"question": "what is trazo"}), _llm_call(1)],
    )
    unstated = _ScriptedJudge([])
    other = RunWindow("run_2")
    _drive(
        DriftDetector(unstated, every_n_llm_calls=1, min_llm_calls=1),  # type: ignore[arg-type]
        other,
        [_run_started({}, run_id="run_2"), _llm_call(1, run_id="run_2")],
    )

    assert stated.calls[0][0] is not None
    assert "what is trazo" in stated.calls[0][0]
    assert unstated.calls[0][0] is None


def test_drift__only_the_most_recent_exchanges_reach_the_judge() -> None:
    judge = _ScriptedJudge([])
    detector = DriftDetector(
        judge,  # type: ignore[arg-type]
        every_n_llm_calls=1,
        min_llm_calls=1,
        window_exchanges=3,
    )
    window = RunWindow(_RUN_ID)

    _drive(detector, window, [_run_started(), *[_llm_call(i) for i in range(1, 7)]])

    assert [x.event_id for x in judge.calls[-1][1]] == [
        f"evt_llm_{_RUN_ID}_{i}" for i in (4, 5, 6)
    ]


def test_drift__state_is_per_run_and_forget_clears_it() -> None:
    judge = _ScriptedJudge([_OFF, _OFF, _OFF])
    detector = DriftDetector(
        judge,  # type: ignore[arg-type]
        every_n_llm_calls=1,
        confirmations=2,
        min_llm_calls=1,
    )
    run_a, run_b = RunWindow("run_a"), RunWindow("run_b")

    first = _drive(
        detector, run_a, [_run_started(run_id="run_a"), _llm_call(1, run_id="run_a")]
    )
    # Run B's first off-task verdict must not count toward run A's streak.
    second = _drive(
        detector, run_b, [_run_started(run_id="run_b"), _llm_call(1, run_id="run_b")]
    )
    third = _drive(detector, run_a, [_llm_call(2, run_id="run_a")])
    detector.forget("run_a")

    assert first == [] and second == []
    assert len(third) == 1
    assert "run_a" not in detector._runs


def test_drift__ignores_events_that_are_not_model_calls() -> None:
    judge = _ScriptedJudge([])
    detector = DriftDetector(judge, every_n_llm_calls=1, min_llm_calls=1)  # type: ignore[arg-type]
    window = RunWindow(_RUN_ID)

    assert _drive(detector, window, [_run_started()]) == []
    assert judge.calls == []


def test_drift__rejects_nonsense_settings() -> None:
    with pytest.raises(ValueError):
        DriftDetector(_ScriptedJudge([]), every_n_llm_calls=0)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        DriftDetector(_ScriptedJudge([]), confirmations=0)  # type: ignore[arg-type]


# --- the window feeds the judge ---


def test_run_window__keeps_the_goal_and_a_bounded_trail_of_exchanges() -> None:
    window = RunWindow(_RUN_ID)

    for event in [
        _run_started({"question": "q"}),
        *[_llm_call(i) for i in range(1, 12)],
    ]:
        window.record(event)

    assert window.goal == {"question": "q"}
    assert len(window.recent_llm_exchanges) == 6
    assert window.first_exchange is not None
    assert window.first_exchange.event_id == f"evt_llm_{_RUN_ID}_1"
    assert window.recent_llm_exchanges[-1].event_id == f"evt_llm_{_RUN_ID}_11"


# --- the worker ---


async def test_worker__drift_runs_alongside_the_rule_detectors_and_is_freed() -> None:
    bus = InMemoryEventBus()
    judge = _ScriptedJudge([_OFF, _OFF])
    drift = DriftDetector(
        judge,  # type: ignore[arg-type]
        every_n_llm_calls=1,
        confirmations=2,
        min_llm_calls=1,
    )
    raised: list[tuple[str, Detection]] = []

    async def on_detection(event: Event, detection: Detection) -> None:
        raised.append((event.event_id, detection))

    worker = DetectorWorker(
        bus=bus,
        trace_store=InMemoryTraceStore(),
        detectors=[],
        consumer_name="w1",
        on_detection=on_detection,
        drift=drift,
    )
    await worker.ensure_group()
    finished = _event(
        event_id="evt_end",
        seq=9,
        kind="run.finished",
        payload={
            "status": "ok",
            "totals": {
                "events": 4,
                "llm_calls": 2,
                "tool_calls": 0,
                "cost_usd": 0.0,
                "tokens_in": 2,
                "tokens_out": 2,
                "duration_ms": 1.0,
            },
        },
    )
    for event in (_run_started(), _llm_call(1), _llm_call(2)):
        await bus.publish(
            EVENTS_STREAM,
            {"event": EventAdapter.dump_json(event, by_alias=True).decode()},
        )
    await bus.publish(EVENTS_STREAM, {"event": json.dumps(finished)})

    await worker.poll_once(count=10, block_ms=0)

    assert [(eid, d.detector) for eid, d in raised] == [
        (f"evt_llm_{_RUN_ID}_2", "drift")
    ]
    assert _RUN_ID not in drift._runs


# --- configuration ---


def test_build_drift_detector__is_off_unless_enabled() -> None:
    assert build_drift_detector(Settings(feature_drift_detector=False)) is None


def test_build_drift_detector__refuses_to_run_without_a_named_judge_model() -> None:
    with pytest.raises(RuntimeError, match="TRAZO_DRIFT_MODEL"):
        build_drift_detector(Settings(feature_drift_detector=True, drift_model=""))


def test_build_drift_detector__builds_from_settings() -> None:
    detector = build_drift_detector(
        Settings(
            feature_drift_detector=True,
            drift_model="some-model",
            drift_every_n_llm_calls=3,
            drift_confirmations=4,
        )
    )

    assert detector is not None
    assert detector._judge.model == "some-model"
    assert detector._every_n == 3
    assert detector._confirmations == 4
