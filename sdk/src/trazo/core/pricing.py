"""Model pricing: turns a traced ``llm.call``'s token counts into
``cost_usd``, which the run's totals, the budget detector and the cost-cap
policy all read.

Prices are USD per million tokens, matched on the longest model-name
prefix, so dated or tagged ids (``gpt-4o-2024-08-06``,
``claude-sonnet-4-20250514``) find their family. They are a snapshot:
providers change prices, and this table cannot know about a model released
after it was written. ``TRAZO_PRICING_FILE`` names a JSON file of
``{"model-prefix": [input_per_million, output_per_million]}`` entries
that are merged over the built-in table, so a deployment can correct or
extend it without a new SDK release.

Calls answered by a local server (``ollama``, the demos' ``fixture``)
cost nothing. A model the table doesn't know also records 0.0 -- an
under-count, never an invented number; ``log`` says so once per model.

Not modelled: prompt-cache discounts, batch discounts, and tiered prices
(e.g. Claude Haiku 5.5 above 100K input tokens). Each would need usage
detail the adapters don't receive.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)

# Claude: Anthropic first-party rates as of 2026-10. OpenAI and Google:
# list prices as last checked; override with TRAZO_PRICING_FILE.
_BUILTIN_PRICES: dict[str, tuple[float, float]] = {
    # Anthropic
    "claude-fable-5-1": (10.00, 50.00),
    "claude-fable-5": (10.00, 50.00),
    "claude-mythos-5-1": (10.00, 50.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-opus-4-7": (5.00, 25.00),
    "claude-opus-4-6": (5.00, 25.00),
    "claude-opus-4-5": (5.00, 25.00),
    "claude-opus-4-1": (15.00, 75.00),
    "claude-opus-4": (15.00, 75.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-sonnet-4-5": (3.00, 15.00),
    "claude-sonnet-4": (3.00, 15.00),
    "claude-3-7-sonnet": (3.00, 15.00),
    "claude-3-5-sonnet": (3.00, 15.00),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-3-5-haiku": (0.80, 4.00),
    # OpenAI
    "gpt-5-nano": (0.05, 0.40),
    "gpt-5-mini": (0.25, 2.00),
    "gpt-5": (1.25, 10.00),
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "o4-mini": (1.10, 4.40),
    "o3-mini": (1.10, 4.40),
    "o3": (2.00, 8.00),
    "o1-mini": (1.10, 4.40),
    "o1": (15.00, 60.00),
    # Google
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.0-flash": (0.10, 0.40),
}

# Providers whose calls never cost money: local servers and test doubles.
FREE_PROVIDERS = frozenset({"ollama", "fixture", "local", "lmstudio", "llamacpp"})

PRICING_FILE_ENV = "TRAZO_PRICING_FILE"


def normalize_model(model: str) -> str:
    """The bare model name: lowercase, without a router prefix
    (``openai/gpt-4o``), a Bedrock region/vendor prefix
    (``us.anthropic.claude-...``) or a Vertex ``@version`` separator."""
    name = model.strip().lower().rsplit("/", 1)[-1]
    for vendor in ("anthropic.", "openai.", "google."):
        if vendor in name:
            name = name.split(vendor, 1)[1]
    return name.replace("@", "-")


@lru_cache(maxsize=8)
def _prices(pricing_file: str | None) -> dict[str, tuple[float, float]]:
    prices = dict(_BUILTIN_PRICES)
    if not pricing_file:
        return prices
    try:
        overrides = json.loads(Path(pricing_file).read_text(encoding="utf-8"))
        for prefix, (per_m_in, per_m_out) in overrides.items():
            prices[normalize_model(prefix)] = (float(per_m_in), float(per_m_out))
    except (OSError, ValueError, TypeError) as exc:
        log.warning("pricing.invalid_file", path=pricing_file, error=str(exc))
    return prices


_warned_unknown: set[str] = set()


def _is_free_provider(provider: str | None) -> bool:
    # The LangGraph adapter reports the model class (ChatOllama), not a
    # normalized provider id.
    name = (provider or "").lower()
    return name in FREE_PROVIDERS or "ollama" in name


def price_per_million(model: str) -> tuple[float, float] | None:
    """``(input, output)`` USD per million tokens for ``model``, or
    ``None`` when no prefix in the table matches it."""
    name = normalize_model(model)
    prices = _prices(os.environ.get(PRICING_FILE_ENV))
    matches = [prefix for prefix in prices if name.startswith(prefix)]
    if not matches:
        return None
    return prices[max(matches, key=len)]


def estimate_cost_usd(
    *, provider: str | None, model: str | None, tokens_in: int, tokens_out: int
) -> float:
    """``cost_usd`` for one call. 0.0 for a free provider, and for a
    model the table doesn't know (logged once per model)."""
    if _is_free_provider(provider) or not model:
        return 0.0
    price = price_per_million(model)
    if price is None:
        if model not in _warned_unknown:
            _warned_unknown.add(model)
            log.info("pricing.unknown_model", model=model, provider=provider)
        return 0.0
    per_m_in, per_m_out = price
    return (max(tokens_in, 0) * per_m_in + max(tokens_out, 0) * per_m_out) / 1_000_000
