# policies/

OPA policy bundles (TRZ-P6-01/02). Decision semantics are specified in
API_SPEC.md (policy endpoint) and ADR-006.

```
policies/
├── trazo/            # runtime policies -- mounted read-only into the OPA
│                        sidecar by deploy/docker-compose.yml (there is
│                        deliberately no runtime policy-upload endpoint,
│                        ARCHITECTURE §5)
└── tests/trazo/      # opa test files, kept out of the runtime mount so
                         the served data.trazo.decision document never
                         carries test-only helper rules/fixtures
```

Every file in `trazo/` declares `package trazo.decision`; the control
plane evaluates policies with one HTTP call, `POST
opa:8181/v1/data/trazo/decision`, and reads `decision`/`policy_id`/
`reasons` straight off the response (`decision.rego`'s docstring covers
how new policies plug in without conflicting).

Starter policies (`trazo/cost_cap.rego`, `trazo/tool_blocklist.rego`,
`trazo/active_detection.rego`) each contribute to a shared `deny`/
`escalate` set rather than defining `decision` themselves — that's what
lets multiple policy files coexist without one overwriting another's
verdict.

Run the suite locally: `opa test policies/trazo policies/tests/trazo`
(wired into CI, TRZ-P6-01). No live OPA server needed — `opa test`
compiles and evaluates entirely offline.
