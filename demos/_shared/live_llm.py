"""Real LLM calls for demo `--live` mode (TRZ-P3-04).

Deliberately minimal: one function, one provider (OpenAI's chat
completions shape — the closest thing to a lingua franca; many gateways
and other providers emulate this exact JSON shape), via `httpx` (already
an SDK dependency, so no new one is added for this). Demos don't need a
provider-abstraction layer; they need exactly enough to generate real
completions for `--live` runs (TRZ-P3-05's nightly corpus job) and to
refresh a fixture cassette (`cassette.py`) for everyone else.

Any server that speaks this shape works, including a free local one.
Configuration comes from the environment:

- ``TRAZO_DEMO_LLM_BASE_URL``: defaults to OpenAI. Point it at
  ``http://localhost:11434/v1`` to use Ollama, at no cost.
- ``TRAZO_DEMO_LLM_MODEL``: defaults to ``gpt-4o-mini``.
- ``TRAZO_DEMO_API_KEY`` / ``OPENAI_API_KEY``: required only for the
  OpenAI default; a local server such as Ollama needs none.

Field-verified against Ollama serving Qwen2.5 3B: real completions,
traced as real ``llm.call`` events, and replayed at full fidelity.
"""

from __future__ import annotations

import os

import httpx

DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_BASE_URL = "https://api.openai.com/v1"
# Generous: a local model's first request includes loading it onto the GPU.
_TIMEOUT_SECONDS = 120.0


def configured_base_url() -> str:
    return os.environ.get("TRAZO_DEMO_LLM_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def configured_model() -> str:
    return os.environ.get("TRAZO_DEMO_LLM_MODEL", DEFAULT_MODEL)


def configured_provider() -> str:
    """A label for traces: which server actually answered."""
    base_url = configured_base_url()
    if base_url == DEFAULT_BASE_URL:
        return "openai"
    if ":11434" in base_url:
        return "ollama"
    return "openai-compatible"


class LiveLLMError(Exception):
    """Raised when a real completion can't be obtained — missing key,
    transport failure, or an unexpected response shape. Never silently
    substitutes a fallback; that's the caller's decision (see each demo's
    `llm.py`), not this module's."""


def complete(
    prompt: str,
    *,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    client: httpx.Client | None = None,
) -> dict[str, object]:
    """Request one completion for ``prompt``, returning the same
    ``{"response", "tokens_in", "tokens_out"}`` shape every demo's
    ``@trace_llm``-wrapped function already returns, so a live call is a
    drop-in replacement for the deterministic fixture path."""
    model = model or configured_model()
    base_url = (base_url or configured_base_url()).rstrip("/")
    key = (
        api_key
        or os.environ.get("TRAZO_DEMO_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
    )
    if not key:
        if base_url == DEFAULT_BASE_URL:
            raise LiveLLMError(
                "no API key: set TRAZO_DEMO_API_KEY or OPENAI_API_KEY, or point "
                "TRAZO_DEMO_LLM_BASE_URL at a local server such as Ollama"
            )
        # A local server ignores the header; the protocol still wants one.
        key = "unused"

    owns_client = client is None
    http_client = client or httpx.Client(timeout=_TIMEOUT_SECONDS)
    try:
        resp = http_client.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": model, "messages": [{"role": "user", "content": prompt}]},
        )
    except httpx.HTTPError as exc:
        raise LiveLLMError(f"request to {base_url} failed: {exc}") from exc
    finally:
        if owns_client:
            http_client.close()

    if resp.status_code != 200:
        raise LiveLLMError(f"{base_url} returned {resp.status_code}: {resp.text}")

    body = resp.json()
    try:
        text = body["choices"][0]["message"]["content"]
        usage = body.get("usage", {})
    except (KeyError, IndexError) as exc:
        raise LiveLLMError(f"unexpected response shape: {body}") from exc

    return {
        "response": text,
        "tokens_in": usage.get("prompt_tokens", len(prompt.split())),
        "tokens_out": usage.get("completion_tokens", len(text.split())),
    }
