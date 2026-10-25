# demos/_shared (TRZ-P3-04)

Infrastructure shared by both demos' LLM strategy: a recorded-completions
cassette (VCR-style) and a minimal real-LLM client for `--live` mode.
Lane D (`demos/`, per IMPLEMENTATION_PLAN.md's ownership table) — this
doesn't trace anything itself, so it isn't part of the SDK's public API
surface; it's test/demo-local infrastructure, same as the demos that use
it.

## Why a cassette, not just a deterministic stub

Both demos already had a deterministic, zero-API-cost fixture path
(TRZ-P3-02/03) before this task — rule-based `ask_*` functions and a
tag-based `ScriptedLLM`. That stays the default and the fallback: it's
what makes a demo run today, with no cassette ever recorded, no API key,
no network. The cassette is an *additive* upgrade over that baseline:

- **Fixture mode (default)** — `cassette.py`'s `Cassette.get()`. A hit
  replays a previously-recorded real completion, byte for byte. A miss
  falls back to the deterministic stub, so nothing breaks before any
  recording exists.
- **Live mode (`--live`)** — each demo's `run.py` flag, wired through to
  `llm.py`'s `set_live_mode(True)`. Calls `live_llm.complete()` for a real
  completion, records it into the cassette (`cassette.json`, next to each
  demo's other files), and returns it. Always calls live — never replays
  — because the nightly corpus job (TRZ-P3-05) needs a fresh completion
  every run, not the first night's cached one.

## `live_llm.py`

One function (`complete()`), one provider shape (OpenAI's chat
completions JSON — close enough to a lingua franca that many gateways
and other providers emulate it), via `httpx` (already an SDK dependency,
so no new one is added here). Configured from the environment:

| Variable | Default | Purpose |
|---|---|---|
| `TRAZO_DEMO_LLM_BASE_URL` | `https://api.openai.com/v1` | Any server speaking the OpenAI shape |
| `TRAZO_DEMO_LLM_MODEL` | `gpt-4o-mini` | Model name sent to that server |
| `TRAZO_DEMO_API_KEY` / `OPENAI_API_KEY` | none | Required only for the OpenAI default |
| `TRAZO_DEMO_CASSETTE` | `cassette.json` beside the demo | Where `--live` records completions |

Against the OpenAI default with no key, `complete()` raises `LiveLLMError`
— never a silent fallback.

### Zero-cost live mode with Ollama

```bash
ollama pull qwen2.5:3b
export TRAZO_DEMO_LLM_BASE_URL=http://localhost:11434/v1 TRAZO_DEMO_LLM_MODEL=qwen2.5:3b
uv run --project sdk --extra langgraph --extra demos \
    python demos/research-assistant/run.py --live
```

Traced `llm.call` events carry `provider: "ollama"` and the model name.
Those labels are part of each call's fingerprint, and replay never calls
the model, so **replay a live run with the same three variables set plus
`TRAZO_DEMO_LIVE=1`**; without them the replayed calls are labelled
`fixture` and every `llm.call` is reported as a mismatch.

Verified on 2026-10-25 against Ollama 0.40 serving Qwen2.5 3B on a 6 GB
laptop GPU: a 55-event research-assistant run (10 LLM calls, about 100 s)
was stored intact, and replayed at 100% boundary and state fidelity with
no divergences. The OpenAI endpoint itself has not been called; it uses
the same request and response shape.

`test_live_llm.py` covers the request/response contract against a fake
`httpx` transport.

## `cassette.py`

`request_key(name, kwargs)` hashes a canonical (sorted-key) JSON encoding
of the call's identifying arguments — stable regardless of dict
insertion order, distinct per function/tag even with identical argument
values. `Cassette` is a thin JSON-file-backed `get`/`put`/`save`; it loads
eagerly and only ever writes when `save()` is called explicitly, so a
`--live` run killed partway through keeps whatever it recorded up to that
point.

Fully covered by `test_cassette.py` (round-trip, key stability, parent-
directory creation) with no external dependencies — these tests need
neither a network nor an API key.
