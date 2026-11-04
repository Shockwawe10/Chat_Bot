"""Contract and end-to-end tests for POST /ask, with a fake embedder and a fake LLM."""

import json

import httpx
import pytest
from fake_backend import VALID_OUTPUT, FakeLlm, TopicalBackend
from fastapi.testclient import TestClient

from app import api
from app.api import AskResponse, TraceLog, create_app, create_default_app
from app.checker import CheckUnavailable, MiniCheck
from app.chunker import ChunkConfig
from app.generator import ABSTAIN_SENTENCE, LlmUnavailable, PromptTemplate
from app.index import KB_DIR, build, read_manifest
from app.retriever import GuardError, IndexUnavailable, Retriever

PROMPT = PromptTemplate.load("v2")
QUESTION = "How long is the product warranty?"


@pytest.fixture(scope="module")
def index_dir(tmp_path_factory):
    path = tmp_path_factory.mktemp("api") / "index"
    build(KB_DIR, path, ChunkConfig(), TopicalBackend())
    return path


@pytest.fixture
def make_client(index_dir, tmp_path):
    clients = []

    def make(llm=None, backend=None, top_k=5, checker=None):
        make_retriever = lambda: Retriever(index_dir, backend or TopicalBackend(), top_k)
        app = create_app(make_retriever, llm or FakeLlm(), PROMPT, tmp_path / "traces", checker)
        client = TestClient(app)
        client.__enter__()
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.__exit__(None, None, None)


def traces(tmp_path):
    lines = []
    for path in sorted((tmp_path / "traces").glob("*.jsonl")):
        lines += path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def output(answer="The answer.", citations=(1,)):
    return json.dumps({"answer": answer, "citations": list(citations), "status": "answer"})


ABSTENTION = json.dumps({"reason": "The context does not say.", "status": "abstain"})
OLD_FORMAT = json.dumps({"abstained": True, "answer": "Maybe 100 EUR.", "citations": [1]})


def test_question_gets_an_answer_with_sources(make_client):
    body = make_client().post("/ask", json={"question": QUESTION}).json()
    assert body["answer"] == "The answer."
    assert body["abstained"] is False
    assert body["retrieved"][0]["doc_id"] == "warranty"
    assert body["citations"] == [body["retrieved"][0]["chunk_id"]]


def test_response_has_exactly_the_agreed_fields(make_client):
    response = make_client().post("/ask", json={"question": QUESTION})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == set(AskResponse.model_fields)
    assert set(body["retrieved"][0]) == {"chunk_id", "doc_id", "heading_path", "rank", "score", "cited"}
    assert set(body["timings_ms"]) == {"embed", "retrieve", "generate", "total"}
    assert set(body["versions"]) == {"index_fingerprint", "prompt", "llm_digest"}


def test_citation_number_maps_to_the_chunk_at_that_rank(make_client):
    llm = FakeLlm(outputs=[output(citations=[3, 1])])
    body = make_client(llm).post("/ask", json={"question": QUESTION}).json()
    by_rank = {hit["rank"]: hit["chunk_id"] for hit in body["retrieved"]}
    assert body["citations"] == [by_rank[3], by_rank[1]]


def test_only_cited_chunks_are_marked_as_cited(make_client):
    llm = FakeLlm(outputs=[output(citations=[2])])
    body = make_client(llm).post("/ask", json={"question": QUESTION}).json()
    assert [hit["cited"] for hit in body["retrieved"]] == [False, True, False, False, False]


def test_every_retrieved_hit_is_returned(make_client):
    body = make_client(top_k=3).post("/ask", json={"question": QUESTION}).json()
    assert [hit["rank"] for hit in body["retrieved"]] == [1, 2, 3]


def test_prompt_sent_to_the_model_holds_the_question_and_the_chunks(make_client):
    llm = FakeLlm()
    body = make_client(llm).post("/ask", json={"question": QUESTION}).json()
    prompt = llm.calls[0]["prompt"]
    assert QUESTION in prompt
    assert body["retrieved"][0]["heading_path"] in prompt


def test_abstention_has_the_fixed_sentence_and_no_citations(make_client):
    body = make_client(FakeLlm(outputs=[ABSTENTION])).post("/ask", json={"question": QUESTION}).json()
    assert body["answer"] == ABSTAIN_SENTENCE
    assert (body["abstained"], body["citations"], body["flags"]) == (True, [], [])
    assert not any(hit["cited"] for hit in body["retrieved"])


def test_the_reason_is_never_shown_to_the_customer(make_client):
    response = make_client(FakeLlm(outputs=[ABSTENTION])).post("/ask", json={"question": QUESTION})
    assert "The context does not say." not in response.text


def test_old_format_abstention_with_an_answer_is_flagged_and_hides_the_answer(make_client):
    response = make_client(FakeLlm(outputs=[OLD_FORMAT])).post("/ask", json={"question": QUESTION})
    assert response.json()["flags"] == ["abstained_with_answer"]
    assert "100 EUR" not in response.text


def test_flags_reach_the_response(make_client):
    llm = FakeLlm(prompt_eval_count=1)
    assert make_client(llm).post("/ask", json={"question": QUESTION}).json()["flags"] == [
        "prompt_truncated"
    ]


def test_versions_name_what_built_the_answer(index_dir, make_client):
    llm = FakeLlm()
    versions = make_client(llm).post("/ask", json={"question": QUESTION}).json()["versions"]
    assert versions == {
        "index_fingerprint": read_manifest(index_dir)["fingerprint"],
        "prompt": "v2",
        "llm_digest": llm.cfg.digest,
    }


def test_timings_are_recorded(make_client):
    timings = make_client().post("/ask", json={"question": QUESTION}).json()["timings_ms"]
    assert all(value >= 0 for value in timings.values())
    assert timings["total"] >= timings["generate"]
    assert timings["total"] >= timings["embed"]
    assert timings["total"] >= timings["retrieve"]


@pytest.mark.parametrize(
    "payload",
    [
        {"question": ""},
        {"question": "    "},
        {"question": "x" * 1001},
        {"question": 5},
        {"question": None},
        {},
    ],
    ids=["empty", "spaces", "too long", "number", "null", "missing"],
)
def test_invalid_input_is_a_422(make_client, payload):
    assert make_client().post("/ask", json=payload).status_code == 422


def test_question_of_exactly_the_limit_is_accepted(make_client):
    assert make_client().post("/ask", json={"question": "x" * 1000}).status_code == 200


def test_length_is_measured_after_stripping_spaces(make_client):
    llm = FakeLlm()
    response = make_client(llm).post("/ask", json={"question": "  " + "x" * 1000 + "  "})
    assert response.status_code == 200
    assert "  x" not in llm.calls[0]["prompt"]


def test_ollama_down_during_generation_is_a_503(make_client):
    llm = FakeLlm(error=httpx.ConnectError("connection refused"))
    assert make_client(llm).post("/ask", json={"question": QUESTION}).status_code == 503


def test_ollama_error_during_generation_is_a_503(make_client):
    llm = FakeLlm(error=LlmUnavailable("Ollama returned 400"))
    assert make_client(llm).post("/ask", json={"question": QUESTION}).status_code == 503


def test_ollama_down_during_embedding_is_a_503(make_client):
    backend = TopicalBackend()
    client = make_client(backend=backend)

    def down(texts):
        raise httpx.ConnectError("connection refused")

    backend.embed = down
    assert client.post("/ask", json={"question": QUESTION}).status_code == 503


def test_unparseable_output_after_the_retry_is_a_502(make_client):
    llm = FakeLlm(outputs=["bad one", "bad two"])
    assert make_client(llm).post("/ask", json={"question": QUESTION}).status_code == 502


def test_output_that_parses_on_the_retry_is_a_200(make_client):
    llm = FakeLlm(outputs=["bad one", VALID_OUTPUT])
    response = make_client(llm).post("/ask", json={"question": QUESTION})
    assert response.status_code == 200
    assert response.json()["flags"] == ["retried"]


def test_guard_mismatch_refuses_to_start(index_dir, tmp_path):
    backend = TopicalBackend(model="other:1")
    app = create_app(lambda: Retriever(index_dir, backend, 5), FakeLlm(), PROMPT, tmp_path)
    with pytest.raises(GuardError), TestClient(app):
        pass


def test_missing_index_starts_with_a_503_and_recovers_when_the_index_appears(index_dir, tmp_path):
    state = {"ready": False}

    def make_retriever():
        if not state["ready"]:
            raise IndexUnavailable("no index")
        return Retriever(index_dir, TopicalBackend(), 5)

    app = create_app(make_retriever, FakeLlm(), PROMPT, tmp_path / "traces")
    with TestClient(app) as client:
        assert client.post("/ask", json={"question": QUESTION}).status_code == 503
        state["ready"] = True
        assert client.post("/ask", json={"question": QUESTION}).status_code == 200


def test_llm_with_the_wrong_digest_gets_a_503(index_dir, tmp_path):
    llm = FakeLlm()

    def wrong_digest():
        raise LlmUnavailable("digest differs")

    llm.check_pinned = wrong_digest
    app = create_app(lambda: Retriever(index_dir, TopicalBackend(), 5), llm, PROMPT, tmp_path)
    with TestClient(app) as client:
        assert client.post("/ask", json={"question": QUESTION}).status_code == 503


def test_answered_request_writes_one_full_trace(make_client, tmp_path):
    make_client().post("/ask", json={"question": QUESTION})
    records = traces(tmp_path)
    assert len(records) == 1
    record = records[0]
    assert record["question"] == QUESTION
    assert record["status"] == 200
    assert record["prompt_version"] == "v2"
    assert record["prompt_sha256"] == PROMPT.sha256
    assert len(record["hits"]) == 5
    assert "score" in record["hits"][0]
    assert record["raw_outputs"] == [VALID_OUTPUT]
    assert record["parsed"] == {"answer": "The answer.", "abstained": False, "citations": [1], "reason": None}
    assert record["flags"] == []
    assert record["timings_ms"]["total"] >= 0


@pytest.mark.parametrize("raw", [ABSTENTION, OLD_FORMAT], ids=["abstention", "old format"])
def test_abstention_trace_keeps_the_raw_model_output(make_client, tmp_path, raw):
    make_client(FakeLlm(outputs=[raw])).post("/ask", json={"question": QUESTION})
    record = traces(tmp_path)[0]
    assert record["parsed"]["abstained"] is True
    assert record["raw_outputs"] == [raw]


def test_abstention_trace_keeps_the_reason(make_client, tmp_path):
    make_client(FakeLlm(outputs=[ABSTENTION])).post("/ask", json={"question": QUESTION})
    assert traces(tmp_path)[0]["parsed"]["reason"] == "The context does not say."


def test_every_request_adds_a_line(make_client, tmp_path):
    client = make_client()
    client.post("/ask", json={"question": QUESTION})
    client.post("/ask", json={"question": "Another question?"})
    assert [record["question"] for record in traces(tmp_path)] == [QUESTION, "Another question?"]


def test_invalid_request_is_traced(make_client, tmp_path):
    make_client().post("/ask", json={"question": ""})
    assert [record["status"] for record in traces(tmp_path)] == [422]


def test_unparseable_output_is_traced_with_the_raw_text(make_client, tmp_path):
    make_client(FakeLlm(outputs=["bad one", "bad two"])).post("/ask", json={"question": QUESTION})
    record = traces(tmp_path)[0]
    assert (record["status"], record["raw_outputs"]) == (502, ["bad one", "bad two"])


def test_unavailable_service_is_traced(make_client, tmp_path):
    make_client(FakeLlm(error=LlmUnavailable("down"))).post("/ask", json={"question": QUESTION})
    record = traces(tmp_path)[0]
    assert (record["status"], record["error"]) == (503, "down")


class FakeChecker(MiniCheck):
    """The real review, with the sentences in `unsupported` judged unsupported instead of asking Ollama."""

    def __init__(self, unsupported=(), error=None):
        super().__init__("fake-check:1", "fake-check-digest", client=object())
        self.unsupported = set(unsupported)
        self.error = error
        self.pinned = 0

    def check_pinned(self):
        self.pinned += 1

    def verdict(self, sentence, passages):
        if self.error:
            raise self.error
        supported = sentence not in self.unsupported
        return {"sentence": sentence, "supported": supported, "reply": "Yes" if supported else "No"}


def test_answer_the_check_rejects_goes_out_as_the_abstention(make_client, tmp_path):
    llm = FakeLlm(outputs=[output("The warranty is 15 years. It ends on March 2, 2031.")])
    checker = FakeChecker(unsupported=["It ends on March 2, 2031."])
    body = make_client(llm, checker=checker).post("/ask", json={"question": QUESTION}).json()
    assert (body["answer"], body["abstained"], body["citations"]) == (ABSTAIN_SENTENCE, True, [])
    assert "answer_check_failed" in body["flags"]
    assert not any(item["cited"] for item in body["retrieved"])
    record = traces(tmp_path)[0]
    assert "March 2, 2031" in record["raw_outputs"][0]
    assert [item["supported"] for item in record["answer_check"]["verdicts"]] == [True, False]
    assert record["answer_check"]["model"] == "fake-check:1" and record["answer_check"]["ms"] >= 0


def test_answer_the_check_supports_goes_out_unchanged(make_client):
    checker = FakeChecker()
    body = make_client(checker=checker).post("/ask", json={"question": QUESTION}).json()
    assert (body["answer"], body["abstained"]) == ("The answer.", False)
    assert checker.pinned == 1


def test_no_check_means_no_check_in_the_trace(make_client, tmp_path):
    make_client().post("/ask", json={"question": QUESTION})
    assert "answer_check" not in traces(tmp_path)[0]


def test_check_down_is_a_503_not_an_unchecked_answer(make_client):
    client = make_client(checker=FakeChecker(error=CheckUnavailable("minicheck down")))
    assert client.post("/ask", json={"question": QUESTION}).status_code == 503


def test_trace_keeps_non_ascii_text_readable(tmp_path):
    TraceLog(tmp_path).write({"question": "load in kN/m²"})
    text = next(tmp_path.glob("*.jsonl")).read_text(encoding="utf-8")
    assert "kN/m²" in text


def test_default_app_reads_top_k_and_prompt_version(monkeypatch, tmp_path):
    seen = {}

    class FakeRetriever:
        def __init__(self, index_dir, backend, top_k):
            seen["top_k"] = top_k
            raise IndexUnavailable("not needed here")

    def fake_prompt(version):
        seen["prompt"] = version
        return PROMPT

    monkeypatch.setattr(api, "Retriever", FakeRetriever)
    monkeypatch.setattr(PromptTemplate, "load", staticmethod(fake_prompt))
    monkeypatch.setenv("TOP_K", "3")
    monkeypatch.setenv("PROMPT_VERSION", "v9")
    # CI has no .env file, so the pinned models have to come from here.
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:1")
    monkeypatch.setenv("EMBEDDING_DIGEST", "fake-digest")
    monkeypatch.setenv("LLM_MODEL", "fake-llm:1")
    monkeypatch.setenv("LLM_DIGEST", "fake-llm-digest")
    with TestClient(create_default_app()):
        pass
    assert seen == {"top_k": 3, "prompt": "v9"}
