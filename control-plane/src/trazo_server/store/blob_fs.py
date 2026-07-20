"""Filesystem BlobStore: content-addressed, sha256-sharded (MVP, ADR-010).

Blocking file I/O is offloaded via anyio.to_thread per CODING_STANDARDS.md
§1 ("control plane is asyncio-native... except via anyio.to_thread for
blocking drivers") — the filesystem has no async API of its own.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import anyio.to_thread

from trazo_server.errors import BlobNotFoundError
from trazo_server.store.blob_store import BlobRef

_SHA256_PREFIX = "sha256:"


class FilesystemBlobStore:
    """Implements trazo_server.store.blob_store.BlobStore over a local directory.

    Layout: ``<root>/<sha[0:2]>/<sha[2:4]>/<sha>`` — sharded two levels deep
    so no single directory accumulates unbounded entries at demo scale.
    """

    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, digest_hex: str) -> Path:
        return self._root / digest_hex[:2] / digest_hex[2:4] / digest_hex

    async def put(
        self, data: bytes, *, content_type: str = "application/json"
    ) -> BlobRef:
        digest = hashlib.sha256(data).hexdigest()
        path = self._path_for(digest)
        if not await anyio.to_thread.run_sync(path.exists):
            await anyio.to_thread.run_sync(_write_bytes, path, data)
        return BlobRef(
            sha256=f"{_SHA256_PREFIX}{digest}",
            bytes=len(data),
            content_type=content_type,
            storage="fs",
            ref=str(path.relative_to(self._root)),
        )

    async def get(self, sha256: str) -> bytes:
        digest = sha256.removeprefix(_SHA256_PREFIX)
        path = self._path_for(digest)
        if not await anyio.to_thread.run_sync(path.exists):
            raise BlobNotFoundError(sha256)
        return await anyio.to_thread.run_sync(path.read_bytes)

    async def exists(self, sha256: str) -> bool:
        digest = sha256.removeprefix(_SHA256_PREFIX)
        return await anyio.to_thread.run_sync(self._path_for(digest).exists)


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
