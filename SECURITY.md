# Security Policy

## Reporting a vulnerability

Use GitHub's private vulnerability reporting on this repository
(Security tab, "Report a vulnerability"). Please do not open public issues
for suspected vulnerabilities.

## Current security posture (pre-release, be aware before deploying)

Trazo is pre-release software with an MVP-honest security model, documented
in ARCHITECTURE §5 and ADR-009:

- A single static API key guards ingest and policy endpoints; query and
  dashboard endpoints are unauthenticated and intended for localhost or a
  trusted network only.
- The platform is not multi-tenant-safe. Do not expose the control plane or
  dashboard to untrusted networks.
- The SDK redacts configured secret patterns from events before shipping,
  but you remain responsible for what your agents put into prompts and tool
  arguments.

Multi-tenant auth, RBAC, and TLS-everywhere are roadmap items (ROADMAP #7),
not current features.
