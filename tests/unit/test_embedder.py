"""Tests for the embedder: prefixes, truncation, the model pin and vector checks."""

import json

import httpx
import pytest
from dotenv import dotenv_values

from app.embedder import (
    DOCUMENT_PREFIX,
    QUERY_PREFIX,
    Embedder,
    EmbeddingError,
    OllamaBackend,
    check_vector,
)
from app.settings import ROOT
from fake_backend import FakeBackend

MODEL = "nomic-embed-text:v1.5"
DIGEST = "0a109f42"


def ollama(handler):
    client = httpx.Client(base_url="http://test", transport=httpx.MockTransport(handler))
    return OllamaBackend(MODEL, DIGEST, client=client)


def test_documents_carry_exactly_one_document_prefix():
    backend = FakeBackend()
    Embedder(backend).embed_documents(["first", "second"])
    assert backend.inputs == [DOCUMENT_PREFIX + "first", DOCUMENT_PREFIX + "second"]


def test_queries_carry_exactly_one_query_prefix():
    backend = FakeBackend()
    Embedder(backend).embed_query("question")
    assert backend.inputs == [QUERY_PREFIX + "question"]


@pytest.mark.parametrize(
    "method, prefix",
    [("embed_documents", DOCUMENT_PREFIX), ("embed_queries", QUERY_PREFIX)],
)
def test_text_that_already_has_the_prefix_does_not_get_it_twice(method, prefix):
    backend = FakeBackend()
    getattr(Embedder(backend), method)([prefix + prefix + "text"])
    assert backend.inputs == [prefix + "text"]


def test_inputs_are_sent_in_batches_and_keep_their_order():
    backend = FakeBackend()
    texts = [f"text {i}" for i in range(7)]
    vectors = Embedder(backend, batch_size=3).embed_documents(texts)
    assert [len(batch) for batch in backend.batches] == [3, 3, 1]
    assert vectors == Embedder(FakeBackend(), batch_size=7).embed_documents(texts)


def test_input_over_the_context_length_is_an_error_and_is_never_sent():
    backend = FakeBackend(context=20)
    with pytest.raises(EmbeddingError, match="context length"):
        Embedder(backend).embed_documents(["x" * 10])
    assert backend.inputs == []


def test_a_short_answer_from_the_backend_is_an_error():
    backend = FakeBackend()
    backend.embed = lambda texts: []
    with pytest.raises(EmbeddingError, match="got 0 vectors"):
        Embedder(backend).embed_documents(["text"])


def test_dimension_comes_from_the_first_vector_and_binds_the_rest():
    backend = FakeBackend()
    vectors = iter([[1.0, 0.0], [1.0, 0.0, 0.0]])
    backend.embed = lambda texts: [next(vectors) for _ in texts]
    embedder = Embedder(backend)
    with pytest.raises(EmbeddingError, match="expected 2 dimensions"):
        embedder.embed_documents(["first", "second"])
    assert embedder.dim == 2


@pytest.mark.parametrize(
    "vector, message",
    [
        ([1.0], "dimensions"),
        ([float("nan"), 1.0], "not finite"),
        ([float("inf"), 1.0], "not finite"),
        ([0.0, 0.0], "zero norm"),
    ],
)
def test_bad_vectors_are_rejected(vector, message):
    with pytest.raises(EmbeddingError, match=message):
        check_vector(vector, 2)


def test_backend_turns_truncation_off():
    sent = {}

    def handler(request):
        sent.update(json.loads(request.content))
        return httpx.Response(200, json={"embeddings": [[1.0]]})

    ollama(handler).embed(["text"])
    assert sent == {"model": MODEL, "input": ["text"], "truncate": False}


def test_backend_error_from_ollama_is_raised():
    backend = ollama(lambda request: httpx.Response(400, json={"error": "too long"}))
    with pytest.raises(EmbeddingError, match="too long"):
        backend.embed(["text"])


def test_pin_passes_on_the_exact_tag_and_digest():
    models = {"models": [{"name": MODEL, "digest": DIGEST}]}
    ollama(lambda request: httpx.Response(200, json=models)).check_pinned()


def test_pin_fails_on_another_digest():
    models = {"models": [{"name": MODEL, "digest": "other"}]}
    with pytest.raises(EmbeddingError, match="pinned"):
        ollama(lambda request: httpx.Response(200, json=models)).check_pinned()


def test_pin_fails_when_the_model_is_not_installed():
    backend = ollama(lambda request: httpx.Response(200, json={"models": []}))
    with pytest.raises(EmbeddingError, match="not installed"):
        backend.check_pinned()


def test_context_length_is_read_from_the_model():
    info = {"model_info": {"general.name": "x", "nomic-bert.context_length": 2048}}
    assert ollama(lambda request: httpx.Response(200, json=info)).context_length() == 2048


@pytest.mark.parametrize("model", ["nomic-embed-text", "nomic-embed-text:latest", ""])
def test_model_without_an_exact_tag_is_refused(model):
    with pytest.raises(EmbeddingError, match="exact tag"):
        OllamaBackend(model, DIGEST)


def test_model_without_a_digest_is_refused():
    with pytest.raises(EmbeddingError, match="EMBEDDING_DIGEST"):
        OllamaBackend.from_env({"EMBEDDING_MODEL": MODEL})


def test_env_example_pins_the_model():
    backend = OllamaBackend.from_env(dotenv_values(ROOT / ".env.example"))
    assert backend.model == MODEL
    assert len(backend.digest) == 64
