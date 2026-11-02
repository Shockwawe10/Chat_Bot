"""Embedder v1 (baseline): documents and queries go through this one module.

nomic-embed-text needs a different prefix for each, and a missing or doubled
prefix hurts retrieval without any error, so `_with_prefix` is the only place
that adds one. Truncation is off: an input that is too long is an error, not a
silently shortened embedding.
"""

import math

import httpx

from app.settings import read_env

DOCUMENT_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "
BATCH_SIZE = 32
DEFAULT_URL = "http://localhost:11434"
# Every token uses at least one character, and the model adds two special tokens,
# so characters + 2 is an upper bound on the token count.
SPECIAL_TOKENS = 2


class EmbeddingError(RuntimeError):
    pass


def _with_prefix(prefix, text):
    """Return text with exactly one prefix, even if it already starts with one."""
    while text.startswith(prefix):
        text = text[len(prefix) :]
    return prefix + text


def check_vector(vector, dim):
    if len(vector) != dim:
        raise EmbeddingError(f"expected {dim} dimensions, got {len(vector)}")
    if not all(math.isfinite(value) for value in vector):
        raise EmbeddingError("vector has a value that is not finite")
    if not any(vector):
        raise EmbeddingError("vector has zero norm")


def check_pinned(client, model, digest):
    """Fail if the installed model is not the exact one that is pinned."""
    models = client.get("/api/tags").raise_for_status().json()["models"]
    installed = {item["name"]: item["digest"] for item in models}
    if model not in installed:
        raise EmbeddingError(f"{model} is not installed in Ollama")
    if installed[model] != digest:
        raise EmbeddingError(f"{model} has digest {installed[model]}, pinned {digest}")


class OllamaBackend:
    def __init__(self, model, digest, base_url=DEFAULT_URL, client=None):
        tag = model.rpartition(":")[2] if ":" in model else ""
        if not tag or tag == "latest":
            raise EmbeddingError(f"embedding model needs an exact tag, got {model!r}")
        if not digest:
            raise EmbeddingError("EMBEDDING_DIGEST is not set")
        self.model = model
        self.digest = digest
        self.client = client or httpx.Client(base_url=base_url, timeout=120)

    @classmethod
    def from_env(cls, env=None):
        env = read_env() if env is None else env
        return cls(
            env.get("EMBEDDING_MODEL") or "",
            env.get("EMBEDDING_DIGEST") or "",
            env.get("OLLAMA_URL") or DEFAULT_URL,
        )

    def check_pinned(self):
        check_pinned(self.client, self.model, self.digest)

    def context_length(self):
        response = self.client.post("/api/show", json={"model": self.model}).raise_for_status()
        info = response.json()["model_info"]
        return next(value for key, value in info.items() if key.endswith(".context_length"))

    def embed(self, texts):
        payload = {"model": self.model, "input": texts, "truncate": True}
        response = self.client.post("/api/embed", json=payload)
        if response.status_code != 200:
            raise EmbeddingError(f"Ollama returned {response.status_code}: {response.text}")
        return response.json()["embeddings"]


class Embedder:
    def __init__(self, backend, batch_size=BATCH_SIZE):
        self.backend = backend
        self.batch_size = batch_size
        self.dim = None
        self._context_length = None

    def embed_documents(self, texts):
        return self._embed([_with_prefix(DOCUMENT_PREFIX, text) for text in texts])

    def embed_queries(self, texts):
        return self._embed([_with_prefix(QUERY_PREFIX, text) for text in texts])

    def embed_query(self, text):
        return self.embed_queries([text])[0]

    def _embed(self, inputs):
        if self._context_length is None:
            self._context_length = self.backend.context_length()
        for text in inputs:
            if len(text) + SPECIAL_TOKENS > self._context_length:
                raise EmbeddingError(f"input of {len(text)} chars may pass the context length")
        vectors = []
        for start in range(0, len(inputs), self.batch_size):
            batch = inputs[start : start + self.batch_size]
            result = self.backend.embed(batch)
            if len(result) != len(batch):
                raise EmbeddingError(f"sent {len(batch)} inputs, got {len(result)} vectors")
            vectors.extend(result)
        for vector in vectors:
            self.dim = self.dim or len(vector)
            check_vector(vector, self.dim)
        return vectors
