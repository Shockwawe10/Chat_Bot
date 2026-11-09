"""POST /ask: question in, answer with sources, timings and versions out.

Run from the repository root:
    uvicorn app.api:create_default_app --factory --port 8000
"""

import json
import logging
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Annotated

import httpx
from chromadb.errors import ChromaError
from fastapi import FastAPI, HTTPException
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, StringConstraints

from app.agent import (
    Agent,
    ChatGuard,
    OllamaChat,
    Sessions,
    StdioMcpTools,
    agent_prompt,
    lead_contacts,
)
from app.checker import CheckUnavailable, MiniCheck
from app.embedder import EmbeddingError, OllamaBackend
from app.generator import (
    GenerationError,
    LlmUnavailable,
    OllamaLlm,
    PromptTemplate,
    generate,
)
from app.guards import OutputGuard
from app.index import INDEX_DIR
from app.language import ENGLISH_ONLY, is_english
from app.retriever import GuardError, IndexUnavailable, Retriever
from app.settings import ROOT, read_env

DEFAULT_TOP_K = 5
MAX_QUESTION_CHARS = 1000
TRACE_DIR = ROOT / "runs" / "traces"
UNAVAILABLE = (
    httpx.HTTPError,
    IndexUnavailable,
    GuardError,
    LlmUnavailable,
    EmbeddingError,
    ChromaError,
    CheckUnavailable,
)

logger = logging.getLogger(__name__)

Question = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_QUESTION_CHARS)
]


class AskRequest(BaseModel):
    question: Question


class RetrievedChunk(BaseModel):
    chunk_id: str
    doc_id: str
    heading_path: str
    rank: int
    score: float
    cited: bool


class Timings(BaseModel):
    embed: float
    retrieve: float
    generate: float
    total: float


class Versions(BaseModel):
    index_fingerprint: str
    prompt: str
    llm_digest: str


class AskResponse(BaseModel):
    answer: str
    abstained: bool
    citations: list[str]
    retrieved: list[RetrievedChunk]
    flags: list[str]
    timings_ms: Timings
    versions: Versions


SessionId = Annotated[str, StringConstraints(strip_whitespace=True, max_length=64, pattern=r"^[A-Za-z0-9_-]*$")]


class ChatRequest(BaseModel):
    message: Question
    session_id: SessionId | None = None


class ToolCall(BaseModel):
    name: str
    arguments: dict
    result: dict


class Booking(BaseModel):
    survey_id: int
    project_id: str
    survey_date: str
    status: str


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    tool_calls: list[ToolCall]
    flags: list[str]
    booking: Booking | None
    total_ms: float


class TraceLog:
    """Appends one JSON line per request. The Stage 2 harness reads these files."""

    def __init__(self, directory):
        self.directory = directory
        self.lock = threading.Lock()

    def write(self, record):
        now = datetime.now(UTC)
        line = json.dumps({"time": now.isoformat(), **record}, ensure_ascii=False)
        self.directory.mkdir(parents=True, exist_ok=True)
        with self.lock, open(self.directory / f"{now.date()}.jsonl", "a", encoding="utf-8") as file:
            file.write(line + "\n")


def _ms(start, end):
    return round((end - start) * 1000, 1)


def create_app(make_retriever, llm, prompt, trace_dir=TRACE_DIR, checker=None, guard=None, make_agent=None):
    """`make_retriever` opens the index. It may raise, so it can be tried again later.

    `checker`, when given, reads every answer before it is returned (app/checker.py).
    `guard`, when given, blocks foreign contacts, prices and prompt leaks after that (app/guards.py).
    `make_agent`, when given, builds the /chat agent from the knowledge-answer function, so the
    agent's knowledge answers come from this same pipeline (app/agent.py).
    """
    traces = TraceLog(trace_dir)
    state = {"retriever": None}
    sessions = Sessions()

    def connect():
        if state["retriever"] is None:
            retriever = make_retriever()
            llm.check_pinned()
            if checker is not None:
                checker.check_pinned()
            state["retriever"] = retriever
        return state["retriever"]

    @asynccontextmanager
    async def lifespan(app):
        try:
            connect()
        except GuardError:
            raise  # refuse to start on an index built with another model
        except UNAVAILABLE as error:
            logger.warning("starting without the index or Ollama: %s", error)
        yield

    app = FastAPI(title="RAG Support Chatbot", lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def trace_invalid_request(request, error):
        traces.write({"status": 422, "errors": json.loads(json.dumps(error.errors(), default=str))})
        return await request_validation_exception_handler(request, error)

    def english_only(retriever, record, started):
        """The fixed English reply for a question in another language: no retrieval, no model."""
        total = _ms(started, time.perf_counter())
        response = AskResponse(
            answer=ENGLISH_ONLY,
            abstained=False,
            citations=[],
            retrieved=[],
            flags=["not_english"],
            timings_ms=Timings(embed=0.0, retrieve=0.0, generate=0.0, total=total),
            versions=Versions(
                index_fingerprint=retriever.fingerprint, prompt=prompt.version, llm_digest=llm.cfg.digest
            ),
        )
        traces.write(
            {**record, "status": 200, "flags": response.flags, "parsed": {"answer": ENGLISH_ONLY, "abstained": False}}
        )
        return response

    def pipeline(retriever, question, record):
        """Retrieval, generation, answer check and output guard: the answer of /ask, and of /chat's
        knowledge tool. Fills the trace record; returns (hits, result, (embedded, retrieved, generated))."""
        vector = retriever.embed_question(question)
        embedded = time.perf_counter()
        hits = retriever.search(vector, question)
        retrieved = time.perf_counter()
        record["hits"] = [asdict(hit) for hit in hits]
        result = generate(llm, prompt.render(hits, question), len(hits))
        generated = time.perf_counter()
        if checker is not None:
            result, verdicts = checker.review(result, hits)
            record["answer_check"] = {"model": checker.model, "verdicts": verdicts}
        if guard is not None:
            result, problems = guard.review(result)
            record["output_guard"] = problems
        return hits, result, (embedded, retrieved, generated)

    @app.post("/ask", response_model=AskResponse)
    def ask(request: AskRequest):
        question = request.question
        record = {"question": question, "prompt_version": prompt.version, "prompt_sha256": prompt.sha256}
        started = time.perf_counter()
        try:
            retriever = connect()
            if not is_english(question):
                return english_only(retriever, record, started)
            hits, result, (embedded, retrieved, generated) = pipeline(retriever, question, record)
        except GenerationError as error:
            traces.write({**record, "status": 502, "raw_outputs": error.raw_outputs})
            raise HTTPException(502, "the model output could not be parsed") from error
        except UNAVAILABLE as error:
            traces.write({**record, "status": 503, "error": str(error)})
            raise HTTPException(503, f"service unavailable: {error}") from error
        finished = time.perf_counter()

        if checker is not None:
            record["answer_check"]["ms"] = _ms(generated, finished)
        cited = {hits[number - 1].chunk_id for number in result.citations}
        response = AskResponse(
            answer=result.answer,
            abstained=result.abstained,
            citations=[hits[number - 1].chunk_id for number in result.citations],
            retrieved=[
                RetrievedChunk(
                    chunk_id=hit.chunk_id,
                    doc_id=hit.doc_id,
                    heading_path=hit.heading_path,
                    rank=hit.rank,
                    score=hit.score,
                    cited=hit.chunk_id in cited,
                )
                for hit in hits
            ],
            flags=result.flags,
            timings_ms=Timings(
                embed=_ms(started, embedded),
                retrieve=_ms(embedded, retrieved),
                generate=_ms(retrieved, generated),
                total=_ms(started, finished),
            ),
            versions=Versions(
                index_fingerprint=retriever.fingerprint,
                prompt=prompt.version,
                llm_digest=llm.cfg.digest,
            ),
        )
        traces.write(
            {
                **record,
                "status": 200,
                "raw_outputs": result.raw_outputs,
                "parsed": {
                    "answer": result.answer,
                    "abstained": result.abstained,
                    "citations": result.citations,
                    "reason": result.reason,
                },
                "flags": result.flags,
                "timings_ms": response.timings_ms.model_dump(),
            }
        )
        return response

    def answer_question(question):
        """The checked and guarded RAG answer, for the agent's search_knowledge_base tool."""
        record = {"question": question, "prompt_version": prompt.version, "prompt_sha256": prompt.sha256}
        _, result, _ = pipeline(connect(), question, record)
        record["raw_outputs"] = result.raw_outputs
        record["parsed"] = {"answer": result.answer, "abstained": result.abstained, "citations": result.citations, "reason": result.reason}
        return result, record

    agent = make_agent(answer_question) if make_agent else None

    @app.post("/chat", response_model=ChatResponse)
    def chat(request: ChatRequest):
        if agent is None:
            raise HTTPException(404, "the agent is not enabled")
        session = sessions.get(request.session_id)
        started = time.perf_counter()
        try:
            turn = agent.turn(session, request.message)
        except GenerationError as error:
            traces.write({"endpoint": "chat", "session_id": session.session_id, "message": request.message, "status": 502, "raw_outputs": error.raw_outputs})
            raise HTTPException(502, "the model output could not be parsed") from error
        except UNAVAILABLE as error:
            traces.write({"endpoint": "chat", "session_id": session.session_id, "message": request.message, "status": 503, "error": str(error)})
            raise HTTPException(503, f"service unavailable: {error}") from error
        total = _ms(started, time.perf_counter())
        traces.write(
            {"endpoint": "chat", **turn.record, "status": 200, "reply": turn.reply, "flags": turn.flags, "booking": turn.booking, "total_ms": total}
        )
        return ChatResponse(
            session_id=session.session_id,
            reply=turn.reply,
            tool_calls=turn.tool_calls,
            flags=turn.flags,
            booking=turn.booking,
            total_ms=total,
        )

    return app


def create_default_app():
    env = read_env()
    backend = OllamaBackend.from_env(env)
    top_k = int(env.get("TOP_K") or DEFAULT_TOP_K)
    mode = env.get("RETRIEVAL") or "dense"
    prompt = PromptTemplate.load(env.get("PROMPT_VERSION") or "v2")
    return create_app(
        lambda: Retriever(INDEX_DIR, backend, top_k, mode),
        OllamaLlm.from_env(env),
        prompt,
        checker=MiniCheck.from_env(env),
        guard=OutputGuard.from_env(env, prompt),
        make_agent=lambda answer_question: make_default_agent(env, answer_question),
    )


def make_default_agent(env, answer_question):
    """The /chat agent: qwen3 with tools, the MCP server on stdio, the reply guard."""
    from mcp_server.tools import confirm_pending_survey

    _, prompt_text = agent_prompt(env)
    return Agent(
        OllamaChat.from_env(env),
        StdioMcpTools(),
        answer_question,
        ChatGuard(lead_contacts, prompt_text),
        prompt_text,
        confirm=confirm_pending_survey,
    )
