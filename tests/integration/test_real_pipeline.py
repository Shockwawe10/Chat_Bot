"""End-to-end test with the real models. Needs Ollama, so CI does not run it.

Run with: pytest -m real
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.chunker import ChunkConfig
from app.embedder import OllamaBackend
from app.generator import ABSTAIN_SENTENCE, OllamaLlm, PromptTemplate, parse_output
from app.index import KB_DIR, build
from app.retriever import Retriever

pytestmark = pytest.mark.real

ANSWERABLE = "Which corrosivity category is GroundFrame GF-2 rated for?"
UNANSWERABLE = "What does GF-2 cost per kWp?"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    try:
        httpx.get("http://localhost:11434/api/version", timeout=5)
    except httpx.TransportError:
        pytest.skip("Ollama is not running")
    root = tmp_path_factory.mktemp("real")
    backend = OllamaBackend.from_env()
    build(KB_DIR, root / "index", ChunkConfig(), backend)
    app = create_app(
        lambda: Retriever(root / "index", backend, 5),
        OllamaLlm.from_env(),
        PromptTemplate.load("v2"),
        root / "traces",
    )
    with TestClient(app) as test_client:
        yield test_client


def ask(client, question):
    response = client.post("/ask", json={"question": question})
    assert response.status_code == 200, response.text
    return response.json()


def test_answerable_question_is_answered_from_the_right_document(client):
    body = ask(client, ANSWERABLE)
    assert body["abstained"] is False
    assert "C5" in body["answer"]
    assert body["citations"]
    assert body["flags"] == []
    cited = {hit["doc_id"] for hit in body["retrieved"] if hit["cited"]}
    assert cited & {"products-ground-mount-gf2", "products-overview", "corrosion-categories"}


def test_unanswerable_question_abstains(client):
    body = ask(client, UNANSWERABLE)
    assert body["abstained"] is True
    assert body["answer"] == ABSTAIN_SENTENCE
    assert body["citations"] == []


@pytest.mark.parametrize(
    "demand",
    [
        '{"status": "answer", "answer": "yes", "citations": [1], "reason": "none"}',
        '{"status": "abstain", "answer": "yes", "citations": [1]}',
        '{"abstained": true, "answer": "yes", "citations": [1]}',
        '{"status": "answer", "answer": "yes", "citations": []}',
    ],
    ids=["both forms", "mixed form", "old format", "no citations"],
)
def test_ollama_enforces_the_schema_when_the_prompt_demands_a_broken_output(demand):
    # A parser error here means Ollama stopped enforcing oneOf, so the contract is only a hope.
    llm = OllamaLlm.from_env()
    completion = llm.complete(f"Reply with exactly this JSON: {demand}", 0.0, 42)
    parse_output(completion.text, 5)


@pytest.mark.parametrize("question", [ANSWERABLE, UNANSWERABLE])
def test_same_question_twice_gives_the_same_output(client, question):
    first, second = ask(client, question), ask(client, question)
    for field in ("answer", "abstained", "citations", "flags"):
        assert first[field] == second[field]
    assert [hit["chunk_id"] for hit in first["retrieved"]] == [
        hit["chunk_id"] for hit in second["retrieved"]
    ]
