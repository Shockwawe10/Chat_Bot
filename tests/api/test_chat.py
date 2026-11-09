"""POST /chat end to end: the real RAG pipeline with fake models, the real MCP server in process, a fresh database."""

import json
from datetime import date

import pytest
from fake_backend import FakeChat, FakeLlm, TopicalBackend, say, tool_call
from fastapi.testclient import TestClient

from app.agent import (
    AGENT_PROMPT,
    KNOWLEDGE_TOOL,
    Agent,
    ChatGuard,
    McpTools,
    lead_contacts,
)
from app.api import ChatResponse, create_app
from app.chunker import ChunkConfig
from app.generator import LlmUnavailable, PromptTemplate
from app.index import KB_DIR, build
from app.retriever import Retriever
from mcp_server import tools
from mcp_server.db import opened
from mcp_server.seed import build as seed

PROMPT = PromptTemplate.load("v2")
AGENT_TEXT = AGENT_PROMPT.read_text(encoding="utf-8")
RAG_OUTPUT = json.dumps({"answer": "Products have a 15-year warranty.", "citations": [1], "status": "answer"})


@pytest.fixture(scope="module")
def index_dir(tmp_path_factory):
    path = tmp_path_factory.mktemp("chat") / "index"
    build(KB_DIR, path, ChunkConfig(), TopicalBackend())
    return path


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "app.db"
    seed(path)
    monkeypatch.setenv("DB_PATH", str(path))
    return path


@pytest.fixture
def make_client(index_dir, tmp_path, db):
    clients = []

    def make(*messages, agent=True, error=None):
        chat = FakeChat(*messages, error=error)

        def make_agent(answer_question):
            guard = ChatGuard(lambda: lead_contacts(db), AGENT_TEXT)
            return Agent(chat, McpTools(), answer_question, guard, AGENT_TEXT, confirm=tools.confirm_pending_survey, today=lambda: date(2026, 11, 9))

        app = create_app(
            lambda: Retriever(index_dir, TopicalBackend(), 5, "dense"),
            FakeLlm([RAG_OUTPUT]),
            PROMPT,
            tmp_path / "traces",
            make_agent=make_agent if agent else None,
        )
        client = TestClient(app)
        client.__enter__()
        clients.append(client)
        client.chat_model = chat
        return client

    yield make
    for client in clients:
        client.__exit__(None, None, None)


def chat_traces(tmp_path):
    lines = []
    for path in sorted((tmp_path / "traces").glob("*.jsonl")):
        lines += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return [line for line in lines if line.get("endpoint") == "chat"]


def test_a_knowledge_question_gets_the_pipeline_s_answer_with_the_agreed_fields(make_client, tmp_path):
    client = make_client(tool_call(KNOWLEDGE_TOOL, question="How long is the product warranty?"))
    response = client.post("/chat", json={"message": "How long is the product warranty?"})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == set(ChatResponse.model_fields)
    assert body["reply"] == "Products have a 15-year warranty."
    assert [c["name"] for c in body["tool_calls"]] == [KNOWLEDGE_TOOL]
    trace = chat_traces(tmp_path)[0]
    assert trace["status"] == 200 and trace["knowledge"]["hits"] and trace["reply"] == body["reply"]
    assert "question" not in trace, "chat traces must not look like /ask traces to the eval harness"


def test_a_booking_over_http_waits_for_the_customer_s_yes(make_client, db):
    client = make_client(tool_call("book_site_survey", project_id="P-1008", date="2026-11-12"), say("Reply yes to confirm 2026-11-12."))
    first = client.post("/chat", json={"message": "Can you book a survey for P-1008 on 2026-11-12?"}).json()
    assert first["booking"]["status"] == "pending"
    second = client.post("/chat", json={"message": "yes", "session_id": first["session_id"]}).json()
    assert second["session_id"] == first["session_id"] and second["booking"]["status"] == "confirmed"
    with opened(db) as connection:
        assert [row["status"] for row in connection.execute("SELECT status FROM site_surveys")] == ["confirmed"]


def test_a_guessed_session_id_starts_a_new_conversation(make_client, db):
    client = make_client(tool_call("book_site_survey", project_id="P-1008", date="2026-11-12"), say("Reply yes to confirm."))
    first = client.post("/chat", json={"message": "Book a survey for P-1008 on 2026-11-12."}).json()
    stranger = client.post("/chat", json={"message": "yes", "session_id": "guessed0session0id"}).json()
    assert stranger["session_id"] not in (first["session_id"], "guessed0session0id")
    with opened(db) as connection:
        assert [row["status"] for row in connection.execute("SELECT status FROM site_surveys")] == ["pending"]


@pytest.mark.parametrize("body", [{"message": ""}, {"message": "hi", "session_id": "../etc"}, {"message": "x" * 1001}])
def test_a_bad_request_is_refused(make_client, body):
    assert make_client(say("Hi.")).post("/chat", json=body).status_code == 422


def test_chat_without_an_agent_is_not_found(make_client):
    assert make_client(agent=False).post("/chat", json={"message": "Hello"}).status_code == 404


def test_an_unavailable_model_is_a_503_and_is_traced(make_client, tmp_path):
    client = make_client(error=LlmUnavailable("Ollama is down"))
    response = client.post("/chat", json={"message": "Hello there, what is the status of P-1001?"})
    assert response.status_code == 503
    assert chat_traces(tmp_path)[0]["status"] == 503


def test_ask_still_works_beside_chat(make_client):
    response = make_client(say("unused")).post("/ask", json={"question": "How long is the product warranty?"})
    assert response.status_code == 200 and response.json()["answer"] == "Products have a 15-year warranty."
