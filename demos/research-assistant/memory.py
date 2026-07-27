"""Local vector memory for the research-assistant demo (TRZ-P3-02).

Real chromadb (per TASKS/PHASE_3.md's "vector memory (chroma local)"), but
with a small custom embedding function instead of chromadb's default: the
default downloads a ~79MB ONNX model from HuggingFace on first use, which
makes the demo fail (or hang) with no network access — exactly the
"CI runs demos with zero API cost" constraint TRZ-P3-04 sets for the
whole corpus. ``_HashEmbedding`` is a deterministic bag-of-words hash into
a fixed-size vector: no network, no model weights, same text always maps
to the same vector (good for reproducible traces too).

Only ``query``/``save`` are exported for node code to call — both go
through the SDK's public ``trace_memory_read``/``trace_memory_write``
escape hatch (IMPLEMENTATION_PLAN.md's lane table: demos use the SDK's
public API only, never ``trazo.core`` directly).
"""

from __future__ import annotations

import hashlib

import chromadb
from chromadb import Documents, EmbeddingFunction

from trazo import trace_memory_read, trace_memory_write

_VECTOR_DIM = 64


class _HashEmbedding(EmbeddingFunction):  # type: ignore[misc]
    """Deterministic, dependency-free stand-in for a real embedding model:
    each word hashes to one of ``_VECTOR_DIM`` buckets; the resulting
    bag-of-words counts, L2-normalized, are the "embedding". Good enough
    to make related findings score closer than unrelated ones for this
    demo's small, fixed vocabulary — not a claim of real semantic quality.
    """

    def __call__(self, input: Documents) -> list[list[float]]:
        vectors = []
        for text in input:
            vector = [0.0] * _VECTOR_DIM
            for word in text.lower().split():
                bucket = (
                    int(hashlib.sha256(word.encode()).hexdigest(), 16) % _VECTOR_DIM
                )
                vector[bucket] += 1.0
            norm = sum(v * v for v in vector) ** 0.5 or 1.0
            vectors.append([v / norm for v in vector])
        return vectors


class VectorMemory:
    """One collection per research run — call ``save`` after each
    synthesized finding, ``query`` before synthesizing the next one."""

    def __init__(self, *, namespace: str) -> None:
        self._client = chromadb.Client()
        self._collection = self._client.create_collection(
            name=namespace, embedding_function=_HashEmbedding()
        )
        self._next_id = 0

    @trace_memory_read(store="vector")
    def query(self, query: str, k: int) -> list[str]:
        if self._collection.count() == 0:
            return []
        result = self._collection.query(query_texts=[query], n_results=k)
        documents = result["documents"]
        return list(documents[0]) if documents else []

    @trace_memory_write(store="vector")
    def save(self, key_or_ns: str, value: str) -> None:
        self._collection.add(documents=[value], ids=[f"{key_or_ns}-{self._next_id}"])
        self._next_id += 1
