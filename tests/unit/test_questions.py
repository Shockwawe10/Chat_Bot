"""Example customer questions per chunk (app/questions.py) and RETRIEVAL=questions."""

import json
from types import SimpleNamespace

import httpx
import numpy as np
import pytest
from fake_backend import TopicalBackend

from app.chunker import ChunkConfig
from app.embedder import QUERY_PREFIX
from app.generator import LlmConfig, LlmUnavailable
from app.index import KB_DIR, build, open_client, read_manifest
from app.questions import SCHEMA, QuestionsUnavailable, ask, chunk_hash, generate, load
from app.retriever import IndexUnavailable, Retriever


@pytest.fixture(scope="module")
def index_dir(tmp_path_factory):
    path = tmp_path_factory.mktemp("questions") / "index"
    build(KB_DIR, path, ChunkConfig(), TopicalBackend())
    return path


def collection(index_dir):
    return open_client(index_dir).get_collection(read_manifest(index_dir)["active_collection"], embedding_function=None)


def fake_llm(reply=None, status=200):
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        if status != 200:
            return httpx.Response(status, text="boom")
        questions = reply if reply is not None else [f"Question {len(sent)}?"]
        return httpx.Response(200, json={"message": {"content": json.dumps({"questions": questions})}})

    client = httpx.Client(base_url="http://test", transport=httpx.MockTransport(handler))
    return SimpleNamespace(cfg=LlmConfig("fake-llm:1", "fake-digest"), client=client), sent


def write(path, entries):
    path.write_text(json.dumps({"chunks": entries}), encoding="utf-8")
    return path


def entries_for(index_dir, questions_for=lambda chunk_id: ["unrelated zzz qqq"]):
    stored = collection(index_dir).get(include=["documents", "metadatas"])
    return {
        chunk_id: {"chunk_sha256": chunk_hash(meta["heading_path"], text), "questions": questions_for(chunk_id)}
        for chunk_id, text, meta in zip(stored["ids"], stored["documents"], stored["metadatas"])
    }


def test_ask_sends_only_the_passage_with_the_schema_at_temperature_zero():
    llm, sent = fake_llm([" Do you do homes? ", "Do you do homes?", "Is 50 kWp too small?", ""])
    assert ask(llm, "About > Not done", "It does not work on private homes.\r\n") == ["Do you do homes?", "Is 50 kWp too small?"]
    prompt = sent[0]["messages"][0]["content"]
    assert "<passage>\nAbout > Not done\nIt does not work on private homes.\n\n</passage>" in prompt
    assert "$passage" not in prompt
    assert (sent[0]["format"], sent[0]["options"]["temperature"], sent[0]["think"]) == (SCHEMA, 0, False)


def test_ask_turns_an_ollama_error_into_llm_unavailable():
    llm, _ = fake_llm(status=500)
    with pytest.raises(LlmUnavailable):
        ask(llm, "H", "text")


def test_generate_covers_every_chunk_with_its_hash_and_the_prompt_hash(index_dir):
    llm, sent = fake_llm()
    data = generate(collection(index_dir), llm)
    stored = collection(index_dir).get(include=["documents", "metadatas"])
    assert sorted(data["chunks"]) == sorted(stored["ids"]) == list(data["chunks"])
    assert len(sent) == len(stored["ids"])
    for chunk_id, text, meta in zip(stored["ids"], stored["documents"], stored["metadatas"]):
        assert data["chunks"][chunk_id]["chunk_sha256"] == chunk_hash(meta["heading_path"], text)
    assert (data["model"], data["digest"], data["prompt"]) == ("fake-llm:1", "fake-digest", "chunk_questions_v1.txt")
    assert len(data["prompt_sha256"]) == 64


def test_load_refuses_a_missing_file_a_missing_chunk_and_a_changed_chunk(index_dir, tmp_path):
    with pytest.raises(QuestionsUnavailable, match="generate"):
        load(tmp_path / "none.json", collection(index_dir))
    entries = entries_for(index_dir)
    first = next(iter(entries))
    missing = {key: value for key, value in entries.items() if key != first}
    with pytest.raises(QuestionsUnavailable, match="other chunks"):
        load(write(tmp_path / "missing.json", missing), collection(index_dir))
    changed = {**entries, first: {**entries[first], "chunk_sha256": "0" * 64}}
    with pytest.raises(QuestionsUnavailable, match="other chunks"):
        load(write(tmp_path / "changed.json", changed), collection(index_dir))
    assert load(write(tmp_path / "good.json", entries), collection(index_dir))[first] == ["unrelated zzz qqq"]


def test_questions_mode_without_a_file_is_unavailable(index_dir, tmp_path):
    with pytest.raises(IndexUnavailable, match="generate"):
        Retriever(index_dir, TopicalBackend(), 5, "questions", tmp_path / "none.json")


def test_a_matching_example_question_lifts_its_chunk_to_the_top(index_dir, tmp_path):
    target = sorted(entries_for(index_dir))[7]
    question = "yearly check-up what gets looked at"
    entries = entries_for(index_dir, lambda chunk_id: [question] if chunk_id == target else ["unrelated zzz qqq"])
    retriever = Retriever(index_dir, TopicalBackend(), 5, "questions", write(tmp_path / "q.json", entries))
    hits = retriever.retrieve(question)
    assert (hits[0].chunk_id, hits[0].rank) == (target, 1)
    assert hits[0].score == pytest.approx(1.0)
    assert [hit.score for hit in hits] == sorted((hit.score for hit in hits), reverse=True)
    assert [hit.rank for hit in hits] == [1, 2, 3, 4, 5]


def test_score_is_the_best_of_the_chunk_cosine_and_its_question_cosines(index_dir, tmp_path):
    entries = entries_for(index_dir, lambda chunk_id: ["warranty claim photos", "unrelated zzz qqq"])
    retriever = Retriever(index_dir, TopicalBackend(), 3, "questions", write(tmp_path / "q.json", entries))
    question = "warranty claim photos project number"
    backend = TopicalBackend()
    query = np.array(backend._vector(question))
    dense = {hit.chunk_id: hit.score for hit in Retriever(index_dir, backend, 200).retrieve(question)}
    shared = float(np.dot(query, backend._vector("warranty claim photos")))
    for hit in retriever.retrieve(question):
        assert hit.score == pytest.approx(max(dense[hit.chunk_id], shared), abs=1e-4)


def test_unrelated_questions_leave_the_cosine_ranking_alone(index_dir, tmp_path):
    entries = entries_for(index_dir, lambda chunk_id: ["zzz qqq xxv"])
    with_questions = Retriever(index_dir, TopicalBackend(), 5, "questions", write(tmp_path / "q.json", entries))
    question = "How long is the product warranty?"
    dense = Retriever(index_dir, TopicalBackend(), 5).retrieve(question)
    assert [hit.chunk_id for hit in with_questions.retrieve(question)] == [hit.chunk_id for hit in dense]


def test_example_questions_are_embedded_as_queries(index_dir, tmp_path):
    entries = entries_for(index_dir, lambda chunk_id: ["Do you do homes?"])
    backend = TopicalBackend()
    Retriever(index_dir, backend, 5, "questions", write(tmp_path / "q.json", entries))
    assert backend.inputs and all(text == QUERY_PREFIX + "Do you do homes?" for text in backend.inputs)
