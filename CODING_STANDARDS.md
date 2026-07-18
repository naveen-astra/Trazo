# Trazo — Coding Standards

The review bar. Applies to humans and AI agents identically. When this
document and personal taste disagree, this document wins; when this
document is wrong, PR the document.

## 1. Python (SDK + control plane)

- Python versions: the SDK targets ≥ 3.10 (it runs inside user processes;
  agent frameworks commonly support 3.10 — ADR-008), so `sdk/` uses
  3.10-compatible syntax only. The control plane is deployed in our own
  container and targets ≥ 3.11. `ruff` (lint + format, config in root
  `pyproject.toml`), `mypy --strict` on `sdk/src` and `control-plane/src`.
- **Typing is not optional.** Public functions fully annotated;
  `Any` requires a comment explaining why. `# type: ignore` requires a
  linked issue.
- Pydantic v2 models for all wire/data shapes; `@dataclass(frozen=True)`
  for internal value objects; plain classes only for behavior.
- No module-level side effects (imports must be free to reorder). No
  singletons except the SDK's explicitly documented `trazo.init` global.
- Errors: library code raises typed exceptions from a module `errors.py`
  (`TrazoError` root per package); never `except Exception: pass` — the
  narrowest catch that works, always logged.
- Concurrency: SDK background work = single shipper thread + queue (no
  asyncio in SDK core — host apps own their loops); control plane is
  asyncio-native, no thread pools except via `anyio.to_thread` for blocking
  drivers.
- Logging: `structlog` only; never `print`; log records carry `run_id`
  when in run context. Levels: DEBUG dev detail, INFO state changes, WARN
  degraded-but-working, ERROR broken-and-visible.
- Docstrings: every public module/class/function, Google style, first line
  imperative. Comments explain *why*, never narrate the code.

## 2. TypeScript (dashboard)

- `strict: true`, ESLint + Prettier (configs committed). No `any` without
  eslint-disable + reason. API types generated from the OpenAPI spec
  (`make gen-api-types`) — hand-written API types are a bug.
- Components: function components only; server state via TanStack Query
  (no manual fetch-in-useEffect); UI state local or a single lightweight
  store (zustand) — no Redux.
- File naming: `RunTimeline.tsx` (component), `useRunEvents.ts` (hook),
  `runApi.ts` (API module). One component per file.

## 3. Naming conventions (cross-cutting)

- Event kinds: `noun.verb_past` or `noun.noun` exactly as in EVENTS.md —
  code constants mirror the wire strings (`KIND_TOOL_CALL = "tool.call"`).
- IDs: prefixed ULIDs — `run_`, `evt_`, `stp_`, `det_`, `pol_`.
- Env vars: `TRAZO_*` only. Metrics: `trazo_<component>_<name>_<unit>`
  (Prometheus conventions).
- DB: snake_case, singular column names, plural table names; no
  abbreviations except `ts`, `ms`, `usd`.
- Python packages/modules: short lowercase; no `utils.py` — name the
  domain (`fingerprint.py`, `spool.py`). A `utils` module is a review
  reject.

## 4. Design patterns (sanctioned set)

- **Ports & adapters** at every infrastructure seam (`EventBus`,
  `BlobStore`, `TraceStore`, `Detector`) — Protocol classes, MVP impl +
  test fake per port. New infrastructure = new impl of an existing port,
  or an ADR.
- **Strategy** for detectors and adapters; **modes over subclasses** for
  the recorder (RECORD/REPLAY enum, one class).
- Dependency injection by constructor argument; no service locators, no
  framework DI containers. FastAPI `Depends` only in `api/` handlers.
- Forbidden: metaclass magic, `__getattr__` indirection in public paths,
  inheritance deeper than 2, premature generics.

## 5. PR review checklist (the reviewer's script)

1. Maps to exactly one task ID; DoD items checked.
2. Tests prove the behavior (not just execute the code).
3. No contract drift: event shapes, API responses, DB schema match docs —
   or the docs are updated in the same PR.
4. Errors degrade per ARCHITECTURE §7 (especially: SDK cannot crash host).
5. Names follow §3; no sanctioned-pattern violations (§4).
6. Logs/metrics added for new failure modes.
