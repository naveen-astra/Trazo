# dashboard

React + TypeScript (strict) + Vite. Server state via TanStack Query; the
dashboard is a pure API consumer with no business logic of its own
(ARCHITECTURE §2.3). API types are generated from the control plane's
OpenAPI schema (`make gen-api-types`); hand-written API types are a bug.

## Development

```bash
cd dashboard
npm ci
npm run dev      # http://localhost:5173
npm run lint && npm run build
```

The dev server proxies `/v1` to the control plane on `:8420`.

## Where the API is

The dashboard calls the control plane on **its own origin** by default, at
relative `/v1` URLs. Every way it is served routes `/v1` onward: the Vite
dev server's proxy, the dev image's nginx, and Caddy in production. Staying
same-origin is what lets the browser store and send the HttpOnly sign-in
cookie, so sign-in works wherever it is enabled.

Set `VITE_API_BASE_URL` at build time only to call a control plane on a
different origin. Sign-in will then not work unless that origin is served
under the dashboard's own, because the cookie is `SameSite=Strict`.

## Browser tests

```bash
python tests/fixtures/mock_control_plane.py   # in another terminal, on :8420
npm run test:e2e
```

The mock is a dependency-free stand-in serving one canned run. Its sign-in
mode is switched on per request by an `X-Mock-Auth: required` header, which
`tests/login.spec.ts` sends, so the sign-in and open-access specs run in
parallel against one mock. Stop any local stack first: Playwright reuses
whatever already serves `:5173`, and the mock needs `:8420`.
