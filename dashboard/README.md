# dashboard

React + TypeScript (strict) + Vite. Server state via TanStack Query; the
dashboard is a pure API consumer — zero business logic (ARCHITECTURE §2.3).

Status: Phase 0 placeholder page. Feature pages land in TRZ-P2-07 (runs
list + timeline) and Phase 6 (memory inspector, replay stepper, policy
panel). API types will be generated from the control plane's OpenAPI spec
once it exists (`make gen-api-types`, CODING_STANDARDS §2) — hand-written
API types are a bug.

Development:

```bash
cd dashboard
npm ci
npm run dev      # http://localhost:5173, proxies /v1 to :8420
npm run lint && npm run build
```
