"""The systems the harness can score: the real pipeline and three reference systems.

Every system answers `ask(question)` with a dict: answer, abstained, retrieved (chunk ids
in rank order), flags, status and latency_ms. The reference systems are the pre-registered
checks of the harness itself: if they do not score as predicted, the scoring is wrong.
"""

import random
import time

from app.generator import ABSTAIN_SENTENCE
from app.index import INDEX_DIR, open_client, read_manifest


class ServiceUnavailable(RuntimeError):
    pass


class ChunkStore:
    """Chunk text and document by id, read once from the active Chroma collection."""

    def __init__(self, chunks, fingerprint=None):
        self.chunks = chunks  # id: (doc_id, text)
        self.fingerprint = fingerprint

    @classmethod
    def from_index(cls, index_dir=INDEX_DIR):
        manifest = read_manifest(index_dir)
        if manifest is None:
            raise ServiceUnavailable(f"no index in {index_dir}; run: python -m app.index build")
        collection = open_client(index_dir).get_collection(manifest["active_collection"], embedding_function=None)
        found = collection.get(include=["documents", "metadatas"])
        chunks = {
            chunk_id: (metadata["doc_id"], document)
            for chunk_id, document, metadata in zip(found["ids"], found["documents"], found["metadatas"])
        }
        return cls(chunks, manifest["fingerprint"])

    def text(self, chunk_id):
        return self.chunks[chunk_id][1]

    def doc_id(self, chunk_id):
        return self.chunks[chunk_id][0]


class ApiSystem:
    """POST /ask on any client with .post(): FastAPI's TestClient in process, or httpx over HTTP."""

    has_retrieval = has_generation = True

    def __init__(self, client, name="pipeline"):
        self.client = client
        self.name = name
        self.versions = None

    def ask(self, question):
        started = time.perf_counter()
        response = self.client.post("/ask", json={"question": question})
        latency = round((time.perf_counter() - started) * 1000, 1)
        if response.status_code == 503:
            raise ServiceUnavailable(response.text)
        if response.status_code != 200:
            return {"status": response.status_code, "answer": "", "abstained": False, "latency_ms": latency}
        body = response.json()
        self.versions = body["versions"]
        return {
            "status": 200,
            "answer": body["answer"],
            "abstained": body["abstained"],
            "retrieved": [hit["chunk_id"] for hit in body["retrieved"]],
            "flags": body["flags"],
            "latency_ms": latency,
        }


class AlwaysAbstain:
    name = "always-abstain"
    has_retrieval, has_generation = False, True

    def ask(self, question):
        return {"status": 200, "answer": ABSTAIN_SENTENCE, "abstained": True, "latency_ms": 0.0}


class AlwaysAnswer:
    name = "always-answer"
    has_retrieval, has_generation = False, True

    def ask(self, question):
        return {"status": 200, "answer": "Yes.", "abstained": False, "latency_ms": 0.0}


class RandomRetriever:
    """k chunks drawn uniformly without replacement, from a seeded generator."""

    name = "random-retriever"
    has_retrieval, has_generation = True, False

    def __init__(self, store, top_k, seed):
        self.ids = sorted(store.chunks)
        self.top_k = top_k
        self.random = random.Random(seed)

    def ask(self, question):
        return {"status": 200, "retrieved": self.random.sample(self.ids, self.top_k), "latency_ms": 0.0}
