"""The BlobStore port: content-addressed offload for >32KB payload fields.

Filesystem (FilesystemBlobStore) is the MVP implementation; MinIO is an
opt-in swap-in behind this same Protocol (ADR-010), not a rewrite.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class BlobRef:
    """Mirrors one row of ``blobs`` (DATABASE.md §2)."""

    sha256: str
    bytes: int
    content_type: str
    storage: str
    ref: str


class BlobStore(Protocol):
    """Content-addressed blob storage: identical bytes dedupe for free."""

    async def put(
        self, data: bytes, *, content_type: str = "application/json"
    ) -> BlobRef:
        """Store ``data``, keyed by its sha256; writing the same bytes twice
        is a no-op the second time."""
        ...

    async def get(self, sha256: str) -> bytes:
        """Fetch blob bytes by sha256 (with or without the ``sha256:`` prefix).

        Raises trazo_server.errors.BlobNotFoundError if it doesn't exist.
        """
        ...

    async def exists(self, sha256: str) -> bool:
        """True if a blob with this sha256 has already been stored."""
        ...
