"""Retrieval v1 (baseline): top-k cosine search over the active collection.

There is no score threshold: the model decides when to abstain, and a threshold
is a later experiment. The guard refuses an index built with another model,
because those vectors would be compared with query vectors from a different space.
"""

from dataclasses import dataclass

from chromadb.errors import NotFoundError

from app.embedder import DOCUMENT_PREFIX, Embedder, EmbeddingError
from app.index import open_client, read_manifest


class GuardError(RuntimeError):
    """The index was built with other settings. Never query it."""


class IndexUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class Hit:
    chunk_id: str
    doc_id: str
    text: str
    heading_path: str
    rank: int
    score: float


def check_guard(manifest, backend):
    inputs = manifest["inputs"]
    expected = {
        "embedding_model": backend.model,
        "embedding_digest": backend.digest,
        "document_prefix": DOCUMENT_PREFIX,
    }
    for key, value in expected.items():
        if inputs[key] != value:
            raise GuardError(f"index has {key}={inputs[key]!r}, this run has {value!r}")


class Retriever:
    def __init__(self, index_dir, backend, top_k):
        manifest = read_manifest(index_dir)
        if manifest is None:
            raise IndexUnavailable(f"no index manifest in {index_dir}; run: python -m app.index build")
        check_guard(manifest, backend)
        try:
            backend.check_pinned()
        except EmbeddingError as error:
            raise GuardError(str(error)) from error
        try:
            self.collection = open_client(index_dir).get_collection(
                manifest["active_collection"], embedding_function=None
            )
        except NotFoundError as error:
            raise IndexUnavailable(f"active collection is missing: {error}") from error
        self.embedder = Embedder(backend)
        self.top_k = top_k
        self.fingerprint = manifest["fingerprint"]

    def embed_question(self, question):
        return self.embedder.embed_query(question)

    def search(self, vector):
        found = self.collection.query(
            query_embeddings=[vector],
            n_results=min(self.top_k, self.collection.count()),
            include=["documents", "metadatas", "distances"],
        )
        return [
            Hit(
                chunk_id=chunk_id,
                doc_id=metadata["doc_id"],
                text=document,
                heading_path=metadata["heading_path"],
                rank=rank,
                score=1 - distance,
            )
            for rank, (chunk_id, document, metadata, distance) in enumerate(
                zip(
                    found["ids"][0],
                    found["documents"][0],
                    found["metadatas"][0],
                    found["distances"][0],
                ),
                start=1,
            )
        ]

    def retrieve(self, question):
        return self.search(self.embed_question(question))
