# schema/

The canonical, machine-readable event schema — the root of the monorepo's
dependency graph. **Frozen as v1.0** (TRZ-P1-09, see CHANGELOG.md and git
tag `schema-v1.0`). Within v1, only additive changes are allowed (new
optional fields, new event kinds); any change to this schema, additive or
not, must bump `x-trazo-schema-version` — enforced by CI
(`scripts/check_schema_version_bump.py`, wired into `.github/workflows/ci.yml`).
Renames, removals, or semantic changes require a v2 schema and an ADR.

Contents:

- `trace-event.v1.schema.json` — JSON Schema (2020-12) implementing
  [EVENTS.md](../EVENTS.md) exactly: the envelope plus one payload
  definition per event `kind` (§2.1–2.4), selected via `allOf`/`if`/`then`
  on `kind`. Every offloadable field accepts either its inline value or a
  `{"$blob": "sha256:..."}` reference. The four replay-critical boundary
  kinds (`llm.call`, `tool.call`, `memory.read`, `memory.write`) plus
  `human.checkpoint` require `fingerprint` at the envelope level, per
  EVENTS.md §2.3–2.4. Carries `x-trazo-schema-version` at the top level —
  the single source of truth the CI freeze check compares against.
- `examples/sample_run.ndjson` — the EVENTS.md §6 nine-event minimal run
  (LangGraph `plan` → `search` steps), fleshed out with realistic payloads.
  Validates against the schema; shared fixture for SDK, control-plane, and
  (later) benchmark tests.
- OTel GenAI semconv pinned revision reference (ADR-005): **not yet
  pinned.** `llm.call`'s field names (`provider`, `model`, `tokens_in`,
  `tokens_out`, ...) predate this freeze and haven't been checked field-by-
  field against a specific semantic-conventions release; pinning a
  revision here without doing that comparison would be a decoration, not a
  contract. Tracked as a follow-up — see ADR-005's "pin the referenced
  revision" note.

Rules (binding — this is v1, frozen):

- Additive-only within v1 (new optional fields, new kinds). Renames,
  removals, semantic changes → v2 + ADR.
- Any change here requires review from lanes A and B, a version note in
  this file and CHANGELOG.md, and a bump to `x-trazo-schema-version`.
