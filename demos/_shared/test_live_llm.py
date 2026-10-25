"""Unit tests for live_llm.complete()'s request/response contract
(TRZ-P3-04) — a fake transport, not a real call: no LLM API key is
available in this environment (see live_llm.py's module docstring)."""

from __future__ import annotations

import httpx
import pytest
from live_llm import LiveLLMError, complete, configured_provider


def _client(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=handler)


def test_complete__no_api_key_raises_without_a_network_call() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should not be called with no API key")

    with pytest.raises(LiveLLMError, match="no API key"):
        complete(
            "hello",
            api_key=None,
            client=_client(httpx.MockTransport(handler)),
        )


def test_complete__parses_choices_and_usage_from_a_successful_response() -> None:
    seen_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "the answer"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2},
            },
        )

    result = complete(
        "what is trazo",
        api_key="k",
        client=_client(httpx.MockTransport(handler)),
    )

    assert result == {"response": "the answer", "tokens_in": 3, "tokens_out": 2}
    assert seen_requests[0].headers["authorization"] == "Bearer k"
    assert seen_requests[0].url.path.endswith("/chat/completions")


def test_complete__non_200_raises_liveLLMError_with_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal error")

    with pytest.raises(LiveLLMError, match="500"):
        complete("hi", api_key="k", client=_client(httpx.MockTransport(handler)))


def test_complete__unexpected_shape_raises_liveLLMError() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    with pytest.raises(LiveLLMError, match="unexpected response shape"):
        complete("hi", api_key="k", client=_client(httpx.MockTransport(handler)))


def test_complete__missing_usage_falls_back_to_word_count() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "four word answer here"}}]}
        )

    result = complete(
        "a b c", api_key="k", client=_client(httpx.MockTransport(handler))
    )

    assert result == {
        "response": "four word answer here",
        "tokens_in": 3,
        "tokens_out": 4,
    }


def test_complete__a_local_server_needs_no_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TRAZO_DEMO_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "local answer"}}]}
        )

    result = complete(
        "hello",
        model="qwen2.5:3b",
        base_url="http://localhost:11434/v1/",
        client=_client(httpx.MockTransport(handler)),
    )

    assert result["response"] == "local answer"
    assert str(seen[0].url) == "http://localhost:11434/v1/chat/completions"


@pytest.mark.parametrize(
    ("base_url", "provider"),
    [
        (None, "openai"),
        ("https://api.openai.com/v1/", "openai"),
        ("http://localhost:11434/v1", "ollama"),
        ("http://127.0.0.1:8000/v1", "openai-compatible"),
    ],
)
def test_configured_provider__labels_the_server_that_answers(
    monkeypatch: pytest.MonkeyPatch, base_url: str | None, provider: str
) -> None:
    if base_url is None:
        monkeypatch.delenv("TRAZO_DEMO_LLM_BASE_URL", raising=False)
    else:
        monkeypatch.setenv("TRAZO_DEMO_LLM_BASE_URL", base_url)

    assert configured_provider() == provider
