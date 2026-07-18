# trazo-server (control plane)

The FastAPI service owning ingest, query, policy, and live-stream APIs, plus
the in-process store and detector workers (separable later).

Status: Phase 0 stub — `/healthz`, `/readyz`, `/metrics` only. The API
contract is [API_SPEC.md](../API_SPEC.md); storage is
[DATABASE.md](../DATABASE.md); module boundaries are ARCHITECTURE section 2.2.
Implementation begins with TRZ-P1-03 (see
[TASKS/PHASE_1.md](../TASKS/PHASE_1.md)).

Development:

```bash
cd control-plane
uv sync
uv run pytest
uv run python -m trazo_server   # serves on :8420
```
