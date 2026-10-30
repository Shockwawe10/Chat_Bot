"""Tests for retrieval and its startup guard (checks 1 and 2)."""

import numpy as np
import pytest

from app.chunker import ChunkConfig
from app.embedder import DOCUMENT_PREFIX, QUERY_PREFIX, EmbeddingError
from app.index import KB_DIR, build, open_client, read_manifest
from app.retriever import GuardError, Hit, IndexUnavailable, Retriever, check_guard
from fake_backend import TopicalBackend

CFG = ChunkConfig()


@pytest.fixture(scope="module")
def index_dir(tmp_path_factory):
    path = tmp_path_factory.mktemp("retriever") / "index"
    build(KB_DIR, path, CFG, TopicalBackend())
    return path


@pytest.fixture
def retriever(index_dir):
    return Retriever(index_dir, TopicalBackend(), top_k=5)


def test_returns_k_hits_sorted_by_score_and_numbered_from_one(retriever):
    hits = retriever.retrieve("How long is the product warranty?")
    assert len(hits) == 5
    assert all(isinstance(hit, Hit) for hit in hits)
    assert [hit.rank for hit in hits] == [1, 2, 3, 4, 5]
    scores = [hit.score for hit in hits]
    assert scores == sorted(scores, reverse=True)


def test_returns_every_chunk_when_k_is_above_the_count(index_dir, tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "doc.md").write_text("# Title\n\nSome body text.\n", encoding="utf-8")
    path = tmp_path / "small"
    build(kb, path, CFG, TopicalBackend())
    assert len(Retriever(path, TopicalBackend(), top_k=5).retrieve("body text")) == 1


def test_hit_ids_exist_in_the_active_collection(index_dir, retriever):
    hits = retriever.retrieve("wind load and snow load")
    name = read_manifest(index_dir)["active_collection"]
    stored = open_client(index_dir).get_collection(name).get(ids=[hit.chunk_id for hit in hits])
    assert set(stored["ids"]) == {hit.chunk_id for hit in hits}


@pytest.mark.parametrize(
    "question, doc_id",
    [
        ("warranty claim photos project number", "warranty"),
        ("pull-out tests rammed posts screw piles", "foundations-ground-mount"),
        ("sales@example.com working hours", "company-contacts"),
    ],
)
def test_topical_question_finds_the_expected_document(retriever, question, doc_id):
    assert retriever.retrieve(question)[0].doc_id == doc_id


def test_score_is_cosine_similarity(retriever):
    question = "How long is the product warranty?"
    hit = retriever.retrieve(question)[0]
    query = np.array(retriever.embed_question(question))
    stored = retriever.collection.get(ids=[hit.chunk_id], include=["embeddings"])
    assert hit.score == pytest.approx(float(np.dot(query, stored["embeddings"][0])), abs=1e-4)


def test_question_is_embedded_with_the_query_prefix_only_once(index_dir):
    backend = TopicalBackend()
    Retriever(index_dir, backend, top_k=5).retrieve("a question")
    assert backend.inputs == [QUERY_PREFIX + "a question"]


def test_hit_carries_text_heading_and_document(retriever):
    hit = retriever.retrieve("How long is the product warranty?")[0]
    assert hit.doc_id == "warranty"
    assert hit.text
    assert hit.heading_path.startswith("Warranty")


def manifest(model="fake:1", digest="fake-digest", prefix=DOCUMENT_PREFIX):
    return {
        "inputs": {"embedding_model": model, "embedding_digest": digest, "document_prefix": prefix}
    }


def test_guard_accepts_a_matching_manifest():
    check_guard(manifest(), TopicalBackend())


@pytest.mark.parametrize(
    "changed",
    [{"model": "other:1"}, {"digest": "other"}, {"prefix": "other: "}],
    ids=["model", "digest", "prefix"],
)
def test_guard_refuses_a_mismatch(changed):
    with pytest.raises(GuardError):
        check_guard(manifest(**changed), TopicalBackend())


@pytest.mark.parametrize(
    "backend",
    [TopicalBackend(model="other:1"), TopicalBackend(digest="other")],
    ids=["model", "digest"],
)
def test_retriever_refuses_an_index_built_with_another_model(index_dir, backend):
    with pytest.raises(GuardError):
        Retriever(index_dir, backend, top_k=5)


def test_retriever_refuses_when_the_installed_model_is_not_the_pinned_one(index_dir):
    backend = TopicalBackend()

    def wrong_model():
        raise EmbeddingError("digest differs")

    backend.check_pinned = wrong_model
    with pytest.raises(GuardError, match="digest differs"):
        Retriever(index_dir, backend, top_k=5)


def test_missing_manifest_means_the_index_is_unavailable(tmp_path):
    with pytest.raises(IndexUnavailable, match="app.index build"):
        Retriever(tmp_path, TopicalBackend(), top_k=5)


def test_missing_active_collection_means_the_index_is_unavailable(tmp_path):
    path = tmp_path / "index"
    build(KB_DIR, path, CFG, TopicalBackend())
    open_client(path).delete_collection(read_manifest(path)["active_collection"])
    with pytest.raises(IndexUnavailable, match="missing"):
        Retriever(path, TopicalBackend(), top_k=5)
