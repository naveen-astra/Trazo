# policies/

OPA policy bundles, mounted read-only into the OPA sidecar by
`deploy/docker-compose.yml` (there is deliberately no runtime policy-upload
endpoint — ARCHITECTURE §5).

Status: empty until TRZ-P6-01/02, which add the bundle layout, the
`trazo/decision` entrypoint convention, starter policies (cost cap, tool
blocklist, active-detection gate), and `opa test` wiring in CI. Decision
semantics are specified in API_SPEC.md (policy endpoint) and ADR-006.
