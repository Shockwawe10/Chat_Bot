"""Index v1 (baseline): builds one Chroma collection per set of retrieval settings.

The collection name comes from a fingerprint of everything that decides the
vectors, so a run with other settings can never write into an existing collection.
A new collection becomes active only after it passes `verify`.

Run from the repository root:
    python -m app.index build
    python -m app.index prune
"""

import argparse
import hashlib
import json
import logging
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

import chromadb
import numpy as np
from chromadb.api.shared_system_client import SharedSystemClient
from chromadb.config import Settings

from app.chunker import CHUNKER_VERSION, ChunkConfig, chunk, parse_document
from app.embedder import (
    DOCUMENT_PREFIX,
    Embedder,
    EmbeddingError,
    OllamaBackend,
    check_vector,
)
from app.guards import suspicious
from app.settings import ROOT

KB_DIR = ROOT / "data" / "kb"
INDEX_DIR = ROOT / ".chroma"
MANIFEST_NAME = "index_manifest.json"
COLLECTION_PREFIX = "kb_"
ADD_BATCH = 32
EXACT_TOP_K = 10
DISTANCE_TOLERANCE = 1e-4

logger = logging.getLogger(__name__)


class IndexCheckError(RuntimeError):
    pass


@dataclass(frozen=True)
class Corpus:
    chunks: list
    file_hashes: dict  # file name -> sha256 of its bytes
    last_reviewed: dict  # doc_id -> date string or None
    # Chunks left out because they speak to the assistant (app/guards.py): chunk id, doc id, reasons
    quarantined: list = field(default_factory=list)


@dataclass(frozen=True)
class BuildResult:
    status: str  # "up to date", "built" or "reactivated"
    collection: str
    chunk_count: int


def read_corpus(kb_dir, cfg):
    chunks = []
    quarantined = []
    file_hashes = {}
    last_reviewed = {}
    for path in sorted(kb_dir.glob("*.md")):
        data = path.read_bytes()
        text = data.decode("utf-8")
        meta, _ = parse_document(text, path.name)
        file_hashes[path.name] = hashlib.sha256(data).hexdigest()
        last_reviewed[meta.doc_id] = meta.last_reviewed
        for item in chunk(text, meta.doc_id, cfg):
            reasons = suspicious(item.text)
            if reasons:
                quarantined.append({"chunk_id": item.id, "doc_id": item.doc_id, "reasons": reasons})
                logging.getLogger(__name__).warning("%s: left out of the index: %s", item.id, ", ".join(reasons))
            else:
                chunks.append(item)
    return Corpus(chunks, file_hashes, last_reviewed, quarantined)


def fingerprint_inputs(corpus, cfg, backend):
    inputs = {
        "corpus": corpus.file_hashes,
        "chunker_version": CHUNKER_VERSION,
        "chunk_config": asdict(cfg),
        "embedding_model": backend.model,
        "embedding_digest": backend.digest,
        "document_prefix": DOCUMENT_PREFIX,
    }
    # The scan changes which chunks are indexed, so the same files with chunks left out are
    # another index. Only added when something is left out, so a clean corpus keeps its fingerprint.
    if corpus.quarantined:
        inputs["quarantined"] = sorted(item["chunk_id"] for item in corpus.quarantined)
    return inputs


def fingerprint(inputs):
    return hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()


def metadata_for(item, corpus):
    metadata = {
        "doc_id": item.doc_id,
        "start": item.start,
        "end": item.end,
        "chunk_index": item.chunk_index,
        "heading_path": " > ".join(item.heading_path),
        "index_text": item.index_text,
        "chunker_version": item.chunker_version,
    }
    reviewed = corpus.last_reviewed.get(item.doc_id)
    if reviewed is not None:
        metadata["last_reviewed"] = reviewed
    return metadata


def read_manifest(index_dir):
    path = index_dir / MANIFEST_NAME
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _write_manifest(index_dir, manifest):
    """Replace the manifest in one step, so a crash cannot leave half a file."""
    path = index_dir / MANIFEST_NAME
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def open_client(index_dir):
    # Chroma reuses one system per path within a process, and that system can fail to
    # read a collection written earlier ("Nothing found on disk") though a new one reads it.
    SharedSystemClient.clear_system_cache()
    return chromadb.PersistentClient(
        path=str(index_dir), settings=Settings(anonymized_telemetry=False)
    )


def _collection_names(client):
    return {collection.name for collection in client.list_collections()}


def _create_collection(client, name):
    # Set the metric explicitly: Chroma's default is L2.
    return client.create_collection(
        name, configuration={"hnsw": {"space": "cosine"}}, embedding_function=None
    )


def _fill(collection, corpus, embedder):
    vectors = embedder.embed_documents([item.index_text for item in corpus.chunks])
    for start in range(0, len(corpus.chunks), ADD_BATCH):
        batch = corpus.chunks[start : start + ADD_BATCH]
        collection.add(
            ids=[item.id for item in batch],
            embeddings=vectors[start : start + ADD_BATCH],
            documents=[item.text for item in batch],
            metadatas=[metadata_for(item, corpus) for item in batch],
        )


def _read_stored(collection):
    stored = collection.get(include=["embeddings", "metadatas", "documents"])
    return {
        id_: {"vector": vector, "metadata": metadata, "document": document}
        for id_, vector, metadata, document in zip(
            stored["ids"], stored["embeddings"], stored["metadatas"], stored["documents"]
        )
    }


def check_completeness(collection, corpus, stored):
    expected = {item.id for item in corpus.chunks}
    if collection.count() != len(corpus.chunks) or set(stored) != expected:
        raise IndexCheckError(
            f"completeness: collection has {collection.count()} items, expected {len(expected)}"
        )


def check_integrity(corpus, stored, dim):
    for item in corpus.chunks:
        entry = stored[item.id]
        try:
            check_vector([float(value) for value in entry["vector"]], dim)
        except EmbeddingError as error:
            raise IndexCheckError(f"integrity: {item.id}: {error}") from error
        if entry["metadata"] != metadata_for(item, corpus) or entry["document"] != item.text:
            raise IndexCheckError(f"integrity: {item.id}: stored data differs from the chunk")


def check_alignment(corpus, found):
    for item, top_ids in zip(corpus.chunks, found["ids"]):
        if top_ids[0] != item.id:
            raise IndexCheckError(f"alignment: {item.id} retrieved {top_ids[0]} at rank 1")


def _unit(vectors):
    return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


def check_exactness(collection, corpus, stored, queries, found):
    space = collection.configuration["hnsw"]["space"]
    if space != "cosine":
        raise IndexCheckError(f"exactness: collection metric is {space}, not cosine")
    ids = [item.id for item in corpus.chunks]
    vectors = _unit(np.array([stored[id_]["vector"] for id_ in ids], dtype=float))
    similarity = _unit(np.array(queries, dtype=float)) @ vectors.T
    top_k = len(found["ids"][0])
    ranked = np.argsort(-similarity, axis=1, kind="stable")[:, :top_k]
    for row, item in enumerate(corpus.chunks):
        if found["ids"][row] != [ids[position] for position in ranked[row]]:
            raise IndexCheckError(f"exactness: {item.id}: top {top_k} differs from brute force")
        # Normalised vectors rank the same under L2, so also compare the distances.
        expected = 1 - similarity[row, ranked[row]]
        if not np.allclose(found["distances"][row], expected, atol=DISTANCE_TOLERANCE):
            raise IndexCheckError(f"exactness: {item.id}: distances are not cosine distances")


def verify(collection, corpus, embedder):
    stored = _read_stored(collection)
    check_completeness(collection, corpus, stored)
    queries = embedder.embed_queries([item.index_text for item in corpus.chunks])
    check_integrity(corpus, stored, embedder.dim)
    found = collection.query(
        query_embeddings=queries,
        n_results=min(EXACT_TOP_K, len(corpus.chunks)),
        include=["distances"],
    )
    check_alignment(corpus, found)
    check_exactness(collection, corpus, stored, queries, found)


def _delete_if_present(client, name):
    if name in _collection_names(client):
        client.delete_collection(name)


def build(kb_dir, index_dir, cfg, backend):
    """Make the collection for these settings active, building it only if needed."""
    corpus = read_corpus(kb_dir, cfg)
    if not corpus.chunks:
        raise IndexCheckError(f"no chunks found in {kb_dir}")
    backend.check_pinned()
    inputs = fingerprint_inputs(corpus, cfg, backend)
    full_fingerprint = fingerprint(inputs)
    name = COLLECTION_PREFIX + full_fingerprint[:12]

    index_dir.mkdir(parents=True, exist_ok=True)
    client = open_client(index_dir)
    manifest = read_manifest(index_dir)
    exists = name in _collection_names(client)
    is_active = manifest is not None and manifest["fingerprint"] == full_fingerprint
    if is_active and exists and client.get_collection(name).count() == len(corpus.chunks):
        return BuildResult("up to date", name, len(corpus.chunks))

    embedder = Embedder(backend)
    try:
        if exists:
            collection = client.get_collection(name, embedding_function=None)
        else:
            collection = _create_collection(client, name)
            _fill(collection, corpus, embedder)
        verify(collection, corpus, embedder)
    except IndexCheckError:
        _delete_if_present(client, name)
        raise
    except Exception:
        # An outside error says nothing about a collection kept from an earlier run.
        if not exists:
            _delete_if_present(client, name)
        raise

    _write_manifest(
        index_dir,
        {
            "active_collection": name,
            "fingerprint": full_fingerprint,
            "inputs": inputs,
            "chunk_count": len(corpus.chunks),
            "build_time": datetime.now(UTC).isoformat(),
        },
    )
    return BuildResult("reactivated" if exists else "built", name, len(corpus.chunks))


def prune(index_dir):
    """Delete every collection except the active one. Return the deleted names."""
    manifest = read_manifest(index_dir)
    if manifest is None:
        raise IndexCheckError("no manifest, so the active collection is unknown; nothing deleted")
    client = open_client(index_dir)
    removed = sorted(
        name
        for name in _collection_names(client)
        if name.startswith(COLLECTION_PREFIX) and name != manifest["active_collection"]
    )
    for name in removed:
        client.delete_collection(name)
    return removed


def main():
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Build or prune the Chroma index.")
    parser.add_argument("command", choices=["build", "prune"])
    command = parser.parse_args().command
    try:
        if command == "prune":
            print(f"removed: {prune(INDEX_DIR) or 'nothing'}")
            return
        cfg = ChunkConfig.from_env()
        print(f"config: target={cfg.target} max={cfg.max} min={cfg.min} chunker={CHUNKER_VERSION}")
        result = build(KB_DIR, INDEX_DIR, cfg, OllamaBackend.from_env())
    except (EmbeddingError, IndexCheckError) as error:
        sys.exit(f"index {command} failed: {error}")
    print(f"{result.status}: {result.collection} ({result.chunk_count} chunks)")


if __name__ == "__main__":
    main()
