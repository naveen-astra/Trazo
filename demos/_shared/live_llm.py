"""Real LLM calls for demo `--live` mode (TRZ-P3-04).

Deliberately minimal: one function, one provider (OpenAI's chat
completions shape — the closest thing to a lingua franca; many gateways
and other providers emulate this exact JSON shape), via `httpx` (already
an SDK dependency, so no new one is added for this). Demos don't need a
provider-abstraction layer; they need exactly enough to generate real
completions for `--live` runs (TRZ-P3-05's nightly corpus job) and to
refresh a fixture cassette (`cassette.py`) for everyone else.

NOTE: this module's actual network path has not been exercised end to
end in this environment — no `OPENAI_API_KEY` (or any other LLM API key)
is available here. `complete()`'s request construction and response
parsing *are* covered by a unit test against a fake transport
(`test_live_llm.py`), but a real call to `https://api.openai.com` has
not been made. Treat the live path as code-complete, not field-verified,
until it's run somewhere with a real key.
"""

from __future__ import annotations

import os

import httpx

DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_BASE_URL = "https://api.openai.com/v1"
_TIMEOUT_SECONDS = 30.0


class LiveLLMError(Exception):
    """Raised when a real completion can't be obtained — missing key,
    transport failure, or an unexpected response shape. Never silently
    substitutes a fallback; that's the caller's decision (see each demo's
    `llm.py`), not this module's."""


def complete(
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    api_key: str | None = None,
    base_url: str = DEFAULT_BASE_URL,
    client: httpx.Client | None = None,
) -> dict[str, object]:
    """Request one completion for ``prompt``, returning the same
    ``{"response", "tokens_in", "tokens_out"}`` shape every demo's
    ``@trace_llm``-wrapped function already returns, so a live call is a
    drop-in replacement for the deterministic fixture path."""
    key = (
        api_key
        or os.environ.get("TRAZO_DEMO_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
    )
    if not key:
        raise LiveLLMError(
            "no API key: set TRAZO_DEMO_API_KEY or OPENAI_API_KEY to run in --live mode"
        )

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
