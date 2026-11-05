"""Tests for retrieval and its startup guard (checks 1 and 2)."""

import numpy as np
import pytest
from fake_backend import TopicalBackend

from app.chunker import ChunkConfig
from app.embedder import DOCUMENT_PREFIX, QUERY_PREFIX, EmbeddingError
from app.index import KB_DIR, build, open_client, read_manifest
from app.keyword import Bm25, fuse
from app.retriever import GuardError, Hit, IndexUnavailable, Retriever, check_guard

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


def test_dense_is_the_default_and_unknown_modes_are_refused(index_dir, retriever):
    assert (retriever.mode, retriever.keyword) == ("dense", None)
    with pytest.raises(ValueError, match="RETRIEVAL must be"):
        Retriever(index_dir, TopicalBackend(), top_k=5, mode="sparse")


def test_hybrid_fuses_the_full_cosine_ranking_with_bm25_over_heading_and_text(index_dir):
    question = "warranty claim photos project number"
    hybrid = Retriever(index_dir, TopicalBackend(), top_k=5, mode="hybrid")
    count = hybrid.collection.count()
    dense = [hit.chunk_id for hit in Retriever(index_dir, TopicalBackend(), top_k=count).retrieve(question)]
    stored = hybrid.collection.get(include=["documents", "metadatas"])
    texts = [f"{meta['heading_path']}\n{text}" for text, meta in zip(stored["documents"], stored["metadatas"])]
    expected = fuse(dense, Bm25(stored["ids"], texts).ranking(question))[:5]
    hits = hybrid.retrieve(question)
    assert [(hit.chunk_id, hit.score) for hit in hits] == [(chunk_id, pytest.approx(score)) for chunk_id, score in expected]
    assert [hit.rank for hit in hits] == [1, 2, 3, 4, 5]
    stored_by_id = dict(zip(stored["ids"], zip(stored["documents"], stored["metadatas"])))
    for hit in hits:
        document, metadata = stored_by_id[hit.chunk_id]
        assert (hit.text, hit.doc_id, hit.heading_path) == (document, metadata["doc_id"], metadata["heading_path"])


def test_hybrid_search_refuses_a_vector_without_its_question(index_dir):
    hybrid = Retriever(index_dir, TopicalBackend(), top_k=5, mode="hybrid")
    with pytest.raises(ValueError, match="question text"):
        hybrid.search(hybrid.embed_question("warranty"))


def test_hybrid_finds_a_chunk_by_a_word_only_in_its_heading(tmp_path):
    # A chunk's text starts with its own heading; the parent headings are only in heading_path.
    kb = tmp_path / "kb"
    kb.mkdir()
    body = "Some ordinary body text about mounting systems and their parts. " * 3
    (kb / "a.md").write_text(f"# Zebra guide\n\n{body}\n\n## Section\n\n{body}\n", encoding="utf-8")
    (kb / "b.md").write_text(f"# Other guide\n\n{body}\n\n## Section\n\n{body}\n", encoding="utf-8")
    build(kb, tmp_path / "index", CFG, TopicalBackend())
    hybrid = Retriever(tmp_path / "index", TopicalBackend(), top_k=2, mode="hybrid")
    stored = hybrid.collection.get(include=["documents", "metadatas"])
    section = next(i for i, meta in enumerate(stored["metadatas"]) if meta["heading_path"] == "Zebra guide > Section")
    assert "zebra" not in stored["documents"][section].lower()
    scores = hybrid.keyword.scores("zebra")
    assert scores[section] > 0
    assert sorted(scores)[:2] == [0.0, 0.0]  # the other guide's two chunks


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
