# trazo (SDK)

The Python SDK that runs inside a user's agent process: recorder, framework
adapters, policy hook, replay driver, and CLI.

Status: Phase 0 scaffold — installable, versioned, empty. The SDK's
architecture and public API are specified in [SDK.md](../SDK.md); the event
contract it emits is [EVENTS.md](../EVENTS.md); replay semantics are
[REPLAY_ENGINE.md](../REPLAY_ENGINE.md). Implementation begins with
TRZ-P2-01 (see [TASKS/PHASE_2.md](../TASKS/PHASE_2.md)).

Development:

```bash
cd sdk
uv sync          # creates .venv, installs deps from uv.lock
uv run pytest
uv run mypy
```
