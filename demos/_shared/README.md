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
so no new one is added here). Reads `TRAZO_DEMO_API_KEY` or
`OPENAI_API_KEY`; raises `LiveLLMError` — never a silent fallback — if
neither is set.

**Not field-verified**: no LLM API key is available in the environment
this was built in. `complete()`'s request/response contract is covered by
`test_live_llm.py` against a fake `httpx` transport, but a real call to
`https://api.openai.com` has never been made. Code-complete, not
live-verified — run it somewhere with a real key before trusting the
network path specifically.

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
