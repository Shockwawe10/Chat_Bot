"""Retrieval: top-k cosine search over the active collection, or hybrid search.

RETRIEVAL=dense (the default) is the v1 baseline. RETRIEVAL=hybrid ranks every chunk
by cosine and by BM25 over its heading and text, and fuses the two rankings
(app/keyword.py). A hybrid hit's score is its fused score, not a cosine.
RETRIEVAL=questions scores every chunk by its best cosine over its own text and its
example customer questions (app/questions.py). The questions are embedded as queries,
so a question is compared with questions.

There is no score threshold: the model decides when to abstain, and a threshold
is a later experiment. The guard refuses an index built with another model,
because those vectors would be compared with query vectors from a different space.
"""

from dataclasses import dataclass

import numpy as np
from chromadb.errors import NotFoundError

from app.embedder import DOCUMENT_PREFIX, Embedder, EmbeddingError
from app.index import open_client, read_manifest
from app.keyword import Bm25, fuse
from app.questions import QUESTIONS_FILE, QuestionsUnavailable, load

MODES = ("dense", "hybrid", "questions")


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
    def __init__(self, index_dir, backend, top_k, mode="dense", questions_file=QUESTIONS_FILE):
        if mode not in MODES:
            raise ValueError(f"RETRIEVAL must be one of {MODES}, got {mode!r}")
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
        self.mode = mode
        self.keyword = None
        if mode == "hybrid":
            stored = self.collection.get(include=["documents", "metadatas"])
            texts = [f"{meta['heading_path']}\n{text}" for text, meta in zip(stored["documents"], stored["metadatas"])]
            self.keyword = Bm25(stored["ids"], texts)
        self.question_owners = None
        if mode == "questions":
            try:
                by_chunk = load(questions_file, self.collection)
            except QuestionsUnavailable as error:
                raise IndexUnavailable(str(error)) from error
            self.question_owners = [chunk_id for chunk_id, items in by_chunk.items() for _ in items]
            vectors = np.array(self.embedder.embed_queries([q for items in by_chunk.values() for q in items]))
            self.question_vectors = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)

    def embed_question(self, question):
        return self.embedder.embed_query(question)

    def search(self, vector, question=""):
        if self.keyword is not None:
            return self._hybrid(vector, question)
        if self.question_owners is not None:
            return self._with_questions(vector)
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

    def _hybrid(self, vector, question):
        if not question.strip():
            raise ValueError("hybrid search needs the question text, not only its vector")
        found = self.collection.query(
            query_embeddings=[vector],
            n_results=self.collection.count(),
            include=["documents", "metadatas"],
        )
        stored = {
            chunk_id: (document, metadata)
            for chunk_id, document, metadata in zip(found["ids"][0], found["documents"][0], found["metadatas"][0])
        }
        fused = fuse(found["ids"][0], self.keyword.ranking(question))[: self.top_k]
        return [
            Hit(
                chunk_id=chunk_id,
                doc_id=stored[chunk_id][1]["doc_id"],
                text=stored[chunk_id][0],
                heading_path=stored[chunk_id][1]["heading_path"],
                rank=rank,
                score=score,
            )
            for rank, (chunk_id, score) in enumerate(fused, start=1)
        ]

    def _with_questions(self, vector):
        found = self.collection.query(
            query_embeddings=[vector],
            n_results=self.collection.count(),
            include=["documents", "metadatas", "distances"],
        )
        ids = found["ids"][0]
        best = {chunk_id: 1 - distance for chunk_id, distance in zip(ids, found["distances"][0])}
        query = np.array(vector) / np.linalg.norm(vector)
        for owner, similarity in zip(self.question_owners, self.question_vectors @ query):
            best[owner] = max(best[owner], float(similarity))
        stored = dict(zip(ids, zip(found["documents"][0], found["metadatas"][0])))
        # Stable sort: equal scores keep the cosine order.
        ranked = sorted(ids, key=lambda chunk_id: -best[chunk_id])[: self.top_k]
        return [
            Hit(
                chunk_id=chunk_id,
                doc_id=stored[chunk_id][1]["doc_id"],
                text=stored[chunk_id][0],
                heading_path=stored[chunk_id][1]["heading_path"],
                rank=rank,
                score=best[chunk_id],
            )
            for rank, chunk_id in enumerate(ranked, start=1)
        ]

    def retrieve(self, question):
        return self.search(self.embed_question(question), question)
