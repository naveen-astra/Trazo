# ADR-007: Docker Compose for local orchestration; no Kubernetes in MVP

- **Status:** accepted
- **Date:** 2026-07-18

## Context
Proposal listed Minikube/Kind. The MVP is 4 containers + 2 stores. K8s
adds manifests, cluster lifecycle, and debugging indirection for every
contributor, and exercises no design pressure Compose doesn't (the
services are already stateless-except-stores).

## Decision
`deploy/docker-compose.yml` is the one true local environment
(`make up`). CI uses the same compose file for integration tests. K8s
manifests/Helm arrive post-MVP if/when a hosted tier needs them.

## Consequences
`git clone` → running stack in minutes for every human and CI runner.
Cost: no K8s résumé line in the MVP — irrelevant to the demo, the
benchmark, or the papers. Revisit at hosted-tier design time.
