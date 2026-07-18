# schema/

The canonical, machine-readable event schema — the root of the monorepo's
dependency graph. Authored in task **TRZ-P1-01**; frozen as v1 in
**TRZ-P1-09**. Until then this directory contains only this note.

Will contain:

- `trace-event.v1.schema.json` — JSON Schema implementing
  [EVENTS.md](../EVENTS.md) exactly (envelope + all kind payloads).
- `examples/` — golden fixtures, including `sample_run.ndjson` (the
  EVENTS.md §6 minimal run, fleshed out), shared by SDK, control-plane,
  and benchmark tests.
- OTel GenAI semconv pinned revision reference (per ADR-005): the semconv
  version this schema's vocabulary is aligned against.

Rules (binding once v1 is frozen):

- Additive-only within v1 (new optional fields, new kinds). Renames,
  removals, semantic changes → v2 + ADR.
- Any change here requires review from lanes A and B and a version note
  in this file.
