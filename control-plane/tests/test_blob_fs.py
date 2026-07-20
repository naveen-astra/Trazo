"""Unit tests for FilesystemBlobStore — pure filesystem, no external services."""

from __future__ import annotations

from pathlib import Path

import pytest

from trazo_server.errors import BlobNotFoundError
from trazo_server.store.blob_fs import FilesystemBlobStore


async def test_blob_store__put_then_get_round_trips(tmp_path: Path) -> None:
    store = FilesystemBlobStore(tmp_path)

    ref = await store.put(b"hello world", content_type="text/plain")
    fetched = await store.get(ref.sha256)

    assert fetched == b"hello world"
    assert ref.bytes == len(b"hello world")
    assert ref.storage == "fs"
    assert ref.sha256.startswith("sha256:")


async def test_blob_store__identical_bytes_dedupe_to_the_same_ref(
    tmp_path: Path,
) -> None:
    store = FilesystemBlobStore(tmp_path)

    ref1 = await store.put(b"same content")
    ref2 = await store.put(b"same content")

    assert ref1 == ref2


async def test_blob_store__exists_reflects_prior_put(tmp_path: Path) -> None:
    store = FilesystemBlobStore(tmp_path)
    missing_sha = "sha256:" + "0" * 64

    assert await store.exists(missing_sha) is False

    ref = await store.put(b"tracked bytes")

    assert await store.exists(ref.sha256) is True


async def test_blob_store__get_missing_raises_blob_not_found(tmp_path: Path) -> None:
    store = FilesystemBlobStore(tmp_path)

    with pytest.raises(BlobNotFoundError):
        await store.get("sha256:" + "f" * 64)


async def test_blob_store__get_accepts_bare_hex_without_prefix(
    tmp_path: Path,
) -> None:
    store = FilesystemBlobStore(tmp_path)
    ref = await store.put(b"prefix-agnostic lookup")

    bare_hex = ref.sha256.removeprefix("sha256:")

    assert await store.get(bare_hex) == b"prefix-agnostic lookup"


async def test_blob_store__shards_files_two_levels_deep(tmp_path: Path) -> None:
    store = FilesystemBlobStore(tmp_path)
    ref = await store.put(b"sharding check")
    digest = ref.sha256.removeprefix("sha256:")

    expected = tmp_path / digest[:2] / digest[2:4] / digest
    assert expected.is_file()
