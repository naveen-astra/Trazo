"""Unit tests for trazo.core.pricing and its use on every llm.call path."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from trazo.core import pricing
from trazo.core.context import run_scope
from trazo.core.pricing import estimate_cost_usd, normalize_model, price_per_million
from trazo.core.recorder import Recorder
from trazo.decorators import trace_llm
from trazo.integrations.langgraph.callback_handler import TrazoCallbackHandler


class _FakeShipper:
    def __init__(self) -> None:
        self.enqueued: list[dict[str, Any]] = []

    def enqueue(self, event: dict[str, Any]) -> None:
        self.enqueued.append(event)

    def flush_and_stop(self, *, timeout: float = 5.0) -> None:
        pass


@pytest.fixture(autouse=True)
def _fresh_pricing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(pricing.PRICING_FILE_ENV, raising=False)
    pricing._prices.cache_clear()


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("gpt-4o-mini", "gpt-4o-mini"),
        ("openai/gpt-4o-mini", "gpt-4o-mini"),
        ("us.anthropic.claude-opus-5-5", "claude-opus-5-5"),
        ("claude-opus-4-5@20251101", "claude-opus-4-5-20251101"),
        ("  GPT-4O  ", "gpt-4o"),
    ],
)
def test_normalize_model(model: str, expected: str) -> None:
    assert normalize_model(model) == expected


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("gpt-4o-mini", (0.15, 0.60)),
        # Longest prefix wins: not gpt-4o's price.
        ("gpt-4o-mini-2024-07-18", (0.15, 0.60)),
        ("gpt-4o-2024-08-06", (2.50, 10.00)),
        ("claude-opus-5-5", (4.00, 20.00)),
        # Not claude-opus-4's older, higher price.
        ("claude-opus-4-8", (5.00, 25.00)),
        ("claude-opus-4-20250514", (15.00, 75.00)),
        ("claude-sonnet-4-20250514", (3.00, 15.00)),
        ("o3-mini", (1.10, 4.40)),
        ("some-model-nobody-priced", None),
    ],
)
def test_price_per_million(model: str, expected: tuple[float, float] | None) -> None:
    assert price_per_million(model) == expected


def test_estimate_cost_usd__a_priced_model() -> None:
    cost = estimate_cost_usd(
        provider="openai", model="gpt-4o-mini", tokens_in=1_000_000, tokens_out=500_000
    )
    assert cost == pytest.approx(0.15 + 0.30)


@pytest.mark.parametrize("provider", ["ollama", "fixture", "Ollama", "ChatOllama"])
def test_estimate_cost_usd__local_providers_are_free(provider: str) -> None:
    """A local model can share a name with a priced one; it still costs
    nothing."""
    assert (
        estimate_cost_usd(
            provider=provider, model="gpt-4o", tokens_in=10_000, tokens_out=10_000
        )
        == 0.0
    )


def test_estimate_cost_usd__an_unknown_model_records_zero_not_a_guess() -> None:
    assert (
        estimate_cost_usd(
            provider="openai-compatible",
            model="qwen2.5:3b",
            tokens_in=1_000,
            tokens_out=1_000,
        )
        == 0.0
    )


def test_pricing_file__overrides_and_extends_the_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "prices.json"
    path.write_text(
        json.dumps({"gpt-4o-mini": [1.0, 2.0], "my-gateway/house-model": [3.0, 4.0]}),
        encoding="utf-8",
    )
    monkeypatch.setenv(pricing.PRICING_FILE_ENV, str(path))

    assert price_per_million("gpt-4o-mini") == (1.0, 2.0)
    assert price_per_million("house-model-v2") == (3.0, 4.0)
    assert price_per_million("gpt-4o") == (2.50, 10.00)


def test_pricing_file__an_unreadable_file_keeps_the_built_in_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "prices.json"
    path.write_text("not json", encoding="utf-8")
    monkeypatch.setenv(pricing.PRICING_FILE_ENV, str(path))

    assert price_per_million("gpt-4o-mini") == (0.15, 0.60)


# --- the llm.call paths ---


def _install_recorder() -> _FakeShipper:
    from trazo.core.runtime import _install_recorder_for_tests

    shipper = _FakeShipper()
    _install_recorder_for_tests(Recorder(shipper=shipper))
    return shipper


def test_trace_llm__estimates_cost_when_the_function_reports_none() -> None:
    shipper = _install_recorder()

    @trace_llm(provider="openai", model="gpt-4o-mini")
    def ask(question: str) -> dict[str, Any]:
        return {"response": "a", "tokens_in": 1_000_000, "tokens_out": 0}

    with run_scope("proj") as run_ctx:
        ask("q")

    [event] = shipper.enqueued
    assert event["payload"]["cost_usd"] == pytest.approx(0.15)
    assert run_ctx.totals.cost_usd == pytest.approx(0.15)


def test_trace_llm__a_reported_cost_is_kept_as_is() -> None:
    shipper = _install_recorder()

    @trace_llm(provider="openai", model="gpt-4o-mini")
    def ask(question: str) -> dict[str, Any]:
        return {
            "response": "a",
            "tokens_in": 1_000_000,
            "tokens_out": 0,
            "cost_usd": 2.5,
        }

    with run_scope("proj"):
        ask("q")

    assert shipper.enqueued[0]["payload"]["cost_usd"] == 2.5


def test_langgraph_handler__prices_a_chat_model_call() -> None:
    shipper = _FakeShipper()
    handler = TrazoCallbackHandler(Recorder(shipper=shipper))
    run_id = uuid4()

    with run_scope("proj"):
        handler.on_chat_model_start(
            {"id": ["langchain", "chat_models", "openai", "ChatOpenAI"]},
            [[HumanMessage(content="hi")]],
            run_id=run_id,
            invocation_params={"model": "gpt-4o-mini"},
        )
        handler.on_llm_end(
            LLMResult(
                generations=[[ChatGeneration(message=AIMessage(content="hello"))]],
                llm_output={
                    "token_usage": {
                        "prompt_tokens": 1_000_000,
                        "completion_tokens": 1_000_000,
                    }
                },
            ),
            run_id=run_id,
        )

    [event] = [e for e in shipper.enqueued if e["kind"] == "llm.call"]
    assert event["payload"]["model"] == "gpt-4o-mini"
    assert event["payload"]["cost_usd"] == pytest.approx(0.15 + 0.60)
