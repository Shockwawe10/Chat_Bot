"""Tests for the index: the checks that guard a build, and what a re-run does.

The vectors come from a fake backend, so these run without Ollama. The real model
goes through the same checks every time `python -m app.index build` runs.
"""

import json

import numpy as np
import pytest
from fake_backend import DIM, FakeBackend

from app import index
from app.chunker import ChunkConfig
from app.embedder import DOCUMENT_PREFIX, QUERY_PREFIX, Embedder, EmbeddingError
from app.index import (
    KB_DIR,
    IndexCheckError,
    build,
    fingerprint,
    fingerprint_inputs,
    open_client,
    prune,
    read_corpus,
    read_manifest,
    verify,
)

CFG = ChunkConfig()
TIGHT_CFG = ChunkConfig(target=300, max=800, min=100)


@pytest.fixture
def index_dir(tmp_path):
    return tmp_path / "index"


@pytest.fixture
def built(index_dir):
    """A verified collection, plus what a check needs to look at it again."""
    backend = FakeBackend()
    result = build(KB_DIR, index_dir, CFG, backend)
    collection = open_client(index_dir).get_collection(result.collection, embedding_function=None)
    return collection, read_corpus(KB_DIR, CFG), Embedder(FakeBackend()), backend, result


def collection_names(index_dir):
    return {collection.name for collection in open_client(index_dir).list_collections()}


def test_build_stores_every_chunk_with_its_original_text_and_metadata(built):
    collection, corpus, _, _, result = built
    assert result.status == "built"
    assert result.collection.startswith("kb_")
    assert collection.count() == len(corpus.chunks)
    item = corpus.chunks[0]
    stored = collection.get(ids=[item.id], include=["documents", "metadatas"])
    assert stored["documents"] == [item.text]
    metadata = stored["metadatas"][0]
    assert (metadata["start"], metadata["end"]) == (item.start, item.end)
    assert metadata["heading_path"] == " > ".join(item.heading_path)
    assert metadata["index_text"] == item.index_text
    assert metadata["last_reviewed"] == "2026-10-28"


def test_metadata_omits_a_missing_review_date(index_dir, tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "doc.md").write_text("# Title\n\nSome body text.\n", encoding="utf-8")
    result = build(kb, index_dir, CFG, FakeBackend())
    stored = open_client(index_dir).get_collection(result.collection).get(include=["metadatas"])
    assert "last_reviewed" not in stored["metadatas"][0]


def test_collection_uses_cosine_explicitly(built):
    assert built[0].configuration["hnsw"]["space"] == "cosine"


def test_every_input_carries_exactly_one_correct_prefix(built):
    _, corpus, _, backend, _ = built
    index_texts = {item.index_text for item in corpus.chunks}
    documents = [text for text in backend.inputs if text.startswith(DOCUMENT_PREFIX)]
    queries = [text for text in backend.inputs if text.startswith(QUERY_PREFIX)]
    assert len(documents) + len(queries) == len(backend.inputs)
    assert {text.removeprefix(DOCUMENT_PREFIX) for text in documents} == index_texts
    assert {text.removeprefix(QUERY_PREFIX) for text in queries} == index_texts
    assert not any(DOCUMENT_PREFIX in text.removeprefix(DOCUMENT_PREFIX) for text in documents)
    assert not any(QUERY_PREFIX in text.removeprefix(QUERY_PREFIX) for text in queries)


def test_build_checks_the_model_pin(built):
    assert built[3].pin_checks == 1


def test_manifest_records_the_full_fingerprint_inputs(index_dir, built):
    _, corpus, _, _, result = built
    manifest = read_manifest(index_dir)
    assert manifest["active_collection"] == result.collection
    assert manifest["chunk_count"] == len(corpus.chunks)
    assert manifest["build_time"]
    inputs = manifest["inputs"]
    assert inputs == fingerprint_inputs(corpus, CFG, FakeBackend())
    assert fingerprint(inputs) == manifest["fingerprint"]
    assert result.collection == "kb_" + manifest["fingerprint"][:12]


@pytest.mark.parametrize(
    "cfg, backend",
    [
        (TIGHT_CFG, FakeBackend()),
        (CFG, FakeBackend(model="other:1")),
        (CFG, FakeBackend(digest="other-digest")),
    ],
    ids=["chunk config", "model", "digest"],
)
def test_fingerprint_changes_with_each_input(cfg, backend):
    base = fingerprint(fingerprint_inputs(read_corpus(KB_DIR, CFG), CFG, FakeBackend()))
    assert fingerprint(fingerprint_inputs(read_corpus(KB_DIR, cfg), cfg, backend)) != base


def test_fingerprint_changes_with_corpus_content(tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "doc.md").write_text("# Title\n\nFirst body.\n", encoding="utf-8")
    before = fingerprint(fingerprint_inputs(read_corpus(kb, CFG), CFG, FakeBackend()))
    (kb / "doc.md").write_text("# Title\n\nChanged body.\n", encoding="utf-8")
    assert fingerprint(fingerprint_inputs(read_corpus(kb, CFG), CFG, FakeBackend())) != before


@pytest.mark.parametrize("name", ["chunker_version", "document_prefix"])
def test_fingerprint_covers_version_and_prefix(monkeypatch, name):
    corpus = read_corpus(KB_DIR, CFG)
    base = fingerprint(fingerprint_inputs(corpus, CFG, FakeBackend()))
    constant = {"chunker_version": "CHUNKER_VERSION", "document_prefix": "DOCUMENT_PREFIX"}[name]
    monkeypatch.setattr(index, constant, "changed")
    assert fingerprint(fingerprint_inputs(corpus, CFG, FakeBackend())) != base


def test_second_run_is_a_no_op(index_dir, built):
    before = read_manifest(index_dir)
    backend = FakeBackend()
    result = build(KB_DIR, index_dir, CFG, backend)
    assert result.status == "up to date"
    assert backend.inputs == []
    assert read_manifest(index_dir) == before


def test_other_settings_build_a_new_collection_and_leave_the_first_alone(index_dir, built):
    collection, _, _, _, first = built
    stored_before = collection.get(include=["documents"])
    second = build(KB_DIR, index_dir, TIGHT_CFG, FakeBackend())
    assert second.status == "built"
    assert second.collection != first.collection
    assert collection_names(index_dir) == {first.collection, second.collection}
    assert read_manifest(index_dir)["active_collection"] == second.collection
    assert collection.get(include=["documents"]) == stored_before


def test_going_back_to_old_settings_reuses_the_old_collection(index_dir, built):
    first = built[4]
    build(KB_DIR, index_dir, TIGHT_CFG, FakeBackend())
    backend = FakeBackend()
    result = build(KB_DIR, index_dir, CFG, backend)
    assert (result.status, result.collection) == ("reactivated", first.collection)
    assert read_manifest(index_dir)["active_collection"] == first.collection
    assert not any(text.startswith(DOCUMENT_PREFIX) for text in backend.inputs)


def test_stale_manifest_pointing_at_a_missing_collection_rebuilds(index_dir, built):
    first = built[4]
    open_client(index_dir).delete_collection(first.collection)
    result = build(KB_DIR, index_dir, CFG, FakeBackend())
    assert (result.status, result.collection) == ("built", first.collection)
    assert first.collection in collection_names(index_dir)


def test_failed_embedding_leaves_manifest_alone_and_deletes_the_partial_collection(index_dir, built):
    first = built[4]
    before = read_manifest(index_dir)
    backend = FakeBackend()
    backend.embed = lambda texts: []
    with pytest.raises(EmbeddingError):
        build(KB_DIR, index_dir, TIGHT_CFG, backend)
    assert read_manifest(index_dir) == before
    assert collection_names(index_dir) == {first.collection}


def test_failed_verify_leaves_manifest_alone_and_deletes_the_new_collection(
    index_dir, built, monkeypatch
):
    first = built[4]
    before = read_manifest(index_dir)

    def broken(*args):
        raise IndexCheckError("alignment: broken on purpose")

    monkeypatch.setattr(index, "check_alignment", broken)
    with pytest.raises(IndexCheckError):
        build(KB_DIR, index_dir, TIGHT_CFG, FakeBackend())
    assert read_manifest(index_dir) == before
    assert collection_names(index_dir) == {first.collection}


def test_outside_error_on_a_kept_collection_does_not_delete_it(index_dir, built, monkeypatch):
    # Found through the mutation run: a Chroma read error during reactivation deleted
    # a good collection, because every exception deleted the collection being built.
    first = built[4]
    second = build(KB_DIR, index_dir, TIGHT_CFG, FakeBackend())
    before = read_manifest(index_dir)

    def broken(collection):
        raise RuntimeError("Nothing found on disk")

    monkeypatch.setattr(index, "_read_stored", broken)
    with pytest.raises(RuntimeError):
        build(KB_DIR, index_dir, CFG, FakeBackend())
    assert read_manifest(index_dir) == before
    assert collection_names(index_dir) == {first.collection, second.collection}


def test_kept_collection_that_fails_verification_is_deleted_and_rebuilt(index_dir, built):
    _, corpus, _, _, first = built
    build(KB_DIR, index_dir, TIGHT_CFG, FakeBackend())
    open_client(index_dir).get_collection(first.collection).delete(ids=[corpus.chunks[5].id])
    with pytest.raises(IndexCheckError, match="completeness"):
        build(KB_DIR, index_dir, CFG, FakeBackend())
    assert first.collection not in collection_names(index_dir)
    assert build(KB_DIR, index_dir, CFG, FakeBackend()).status == "built"


def test_failed_first_build_writes_no_manifest(index_dir, monkeypatch):
    def broken(*args):
        raise IndexCheckError("broken on purpose")

    monkeypatch.setattr(index, "check_exactness", broken)
    with pytest.raises(IndexCheckError):
        build(KB_DIR, index_dir, CFG, FakeBackend())
    assert read_manifest(index_dir) is None
    assert collection_names(index_dir) == set()


def test_empty_corpus_is_refused(index_dir, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(IndexCheckError, match="no chunks"):
        build(empty, index_dir, CFG, FakeBackend())


def test_verify_passes_on_a_good_collection(built):
    collection, corpus, embedder, _, _ = built
    verify(collection, corpus, embedder)


def test_completeness_catches_a_missing_chunk(built):
    collection, corpus, embedder, _, _ = built
    collection.delete(ids=[corpus.chunks[5].id])
    with pytest.raises(IndexCheckError, match="completeness"):
        verify(collection, corpus, embedder)


def test_completeness_catches_a_replaced_id(built):
    collection, corpus, embedder, _, _ = built
    item = corpus.chunks[5]
    collection.delete(ids=[item.id])
    collection.add(ids=["other"], embeddings=[[1.0] * DIM], documents=["x"], metadatas=[{"a": 1}])
    with pytest.raises(IndexCheckError, match="completeness"):
        verify(collection, corpus, embedder)


def test_integrity_catches_a_zero_vector(built):
    collection, corpus, embedder, _, _ = built
    collection.update(ids=[corpus.chunks[5].id], embeddings=[[0.0] * DIM])
    with pytest.raises(IndexCheckError, match="integrity"):
        verify(collection, corpus, embedder)


def test_integrity_catches_changed_offsets(built):
    collection, corpus, embedder, _, _ = built
    item = corpus.chunks[5]
    metadata = collection.get(ids=[item.id], include=["metadatas"])["metadatas"][0]
    collection.update(ids=[item.id], metadatas=[{**metadata, "end": item.end + 1}])
    with pytest.raises(IndexCheckError, match="integrity"):
        verify(collection, corpus, embedder)


def test_integrity_catches_changed_text(built):
    collection, corpus, embedder, _, _ = built
    item = corpus.chunks[5]
    vector = collection.get(ids=[item.id], include=["embeddings"])["embeddings"]
    collection.update(ids=[item.id], embeddings=vector, documents=["something else"])
    with pytest.raises(IndexCheckError, match="integrity"):
        verify(collection, corpus, embedder)


def test_alignment_catches_two_swapped_vectors(built):
    collection, corpus, embedder, _, _ = built
    first, second = corpus.chunks[3].id, corpus.chunks[40].id
    vectors = collection.get(ids=[first, second], include=["embeddings"])
    by_id = dict(zip(vectors["ids"], vectors["embeddings"]))
    collection.update(ids=[first, second], embeddings=[by_id[second], by_id[first]])
    with pytest.raises(IndexCheckError, match="alignment"):
        verify(collection, corpus, embedder)


def test_exactness_catches_an_l2_collection_even_when_ranking_is_identical(index_dir, built):
    good, corpus, embedder, _, _ = built
    client = open_client(index_dir)
    wrong = client.create_collection(
        "kb_l2", configuration={"hnsw": {"space": "l2"}}, embedding_function=None
    )
    stored = good.get(include=["embeddings", "documents", "metadatas"])
    wrong.add(
        ids=stored["ids"],
        embeddings=stored["embeddings"],
        documents=stored["documents"],
        metadatas=stored["metadatas"],
    )
    with pytest.raises(IndexCheckError, match="metric is l2"):
        verify(wrong, corpus, embedder)


def test_exactness_catches_distances_that_are_not_cosine(built, monkeypatch):
    collection, corpus, embedder, _, _ = built
    real_query = collection.query

    class Wrapped:
        configuration = collection.configuration
        count = collection.count
        get = collection.get

        @staticmethod
        def query(**kwargs):
            found = real_query(**kwargs)
            found["distances"] = [[d * 2 for d in row] for row in found["distances"]]
            return found

    with pytest.raises(IndexCheckError, match="distances"):
        verify(Wrapped, corpus, embedder)


def test_exactness_catches_a_wrong_top_k_order(built):
    collection, corpus, embedder, _, _ = built
    real_query = collection.query

    class Wrapped:
        configuration = collection.configuration
        count = collection.count
        get = collection.get

        @staticmethod
        def query(**kwargs):
            found = real_query(**kwargs)
            found["ids"] = [row[:1] + row[:0:-1] for row in found["ids"]]
            return found

    with pytest.raises(IndexCheckError, match="brute force"):
        verify(Wrapped, corpus, embedder)


def test_brute_force_top_k_matches_what_numpy_says(built):
    collection, corpus, embedder, _, _ = built
    query = np.array(embedder.embed_query(corpus.chunks[0].index_text))
    stored = collection.get(include=["embeddings"])
    scores = np.array(stored["embeddings"], dtype=float) @ query
    best = stored["ids"][int(np.argmax(scores))]
    assert best == corpus.chunks[0].id


def test_prune_keeps_only_the_active_collection(index_dir, built):
    second = build(KB_DIR, index_dir, TIGHT_CFG, FakeBackend())
    removed = prune(index_dir)
    assert removed == [built[4].collection]
    assert collection_names(index_dir) == {second.collection}


def test_prune_leaves_other_collections_alone(index_dir, built):
    open_client(index_dir).create_collection("notes", embedding_function=None)
    assert prune(index_dir) == []
    assert "notes" in collection_names(index_dir)


def test_prune_without_a_manifest_deletes_nothing(index_dir, tmp_path):
    index_dir.mkdir()
    client = open_client(index_dir)
    client.create_collection("kb_orphan", embedding_function=None)
    with pytest.raises(IndexCheckError, match="no manifest"):
        prune(index_dir)
    assert "kb_orphan" in collection_names(index_dir)


def test_manifest_is_valid_json_on_disk(index_dir, built):
    text = (index_dir / index.MANIFEST_NAME).read_text(encoding="utf-8")
    assert json.loads(text)["active_collection"] == built[4].collection
    assert not (index_dir / "index_manifest.tmp").exists()
