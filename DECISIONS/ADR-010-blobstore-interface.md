# ADR-010: BlobStore interface; filesystem default, MinIO optional

- **Status:** accepted
- **Date:** 2026-07-18

## Context
Large tool outputs don't belong in relational rows (proposal is right).
But MinIO-as-requirement adds a container and S3 client config to every
laptop for what MVP scale (megabytes-to-gigabytes) doesn't need.

## Decision
`BlobStore` Protocol (`put(bytes) -> sha256`, `get(sha256)`,
content-addressed, dedup by construction). Default implementation:
local filesystem volume (`fs`). `MinioBlobStore` ships too but is
opt-in via compose profile (`--profile minio`) and one env var. Inline
threshold 32KB (`TRAZO_BLOB_INLINE_MAX`).

## Consequences
Zero-config default path; S3-compatible path proven but optional;
content addressing gives dedupe and immutable caching for replay bundles
for free. Cost: filesystem blobs aren't shared across machines — fine for
single-node MVP, and the interface is the migration.
