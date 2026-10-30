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

from app.embedder import EmbeddingError, OllamaBackend
from app.generator import (
    GenerationError,
    LlmUnavailable,
    OllamaLlm,
    PromptTemplate,
    generate,
)
from app.index import INDEX_DIR
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


def create_app(make_retriever, llm, prompt, trace_dir=TRACE_DIR):
    """`make_retriever` opens the index. It may raise, so it can be tried again later."""
    traces = TraceLog(trace_dir)
    state = {"retriever": None}

    def connect():
        if state["retriever"] is None:
            retriever = make_retriever()
            llm.check_pinned()
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

    @app.post("/ask", response_model=AskResponse)
    def ask(request: AskRequest):
        question = request.question
        record = {"question": question, "prompt_version": prompt.version, "prompt_sha256": prompt.sha256}
        started = time.perf_counter()
        try:
            retriever = connect()
            vector = retriever.embed_question(question)
            embedded = time.perf_counter()
            hits = retriever.search(vector)
            retrieved = time.perf_counter()
            record["hits"] = [asdict(hit) for hit in hits]
            result = generate(llm, prompt.render(hits, question), len(hits))
        except GenerationError as error:
            traces.write({**record, "status": 502, "raw_outputs": error.raw_outputs})
            raise HTTPException(502, "the model output could not be parsed") from error
        except UNAVAILABLE as error:
            traces.write({**record, "status": 503, "error": str(error)})
            raise HTTPException(503, f"service unavailable: {error}") from error
        finished = time.perf_counter()

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
                generate=_ms(retrieved, finished),
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

    return app


def create_default_app():
    env = read_env()
    backend = OllamaBackend.from_env(env)
    top_k = int(env.get("TOP_K") or DEFAULT_TOP_K)
    return create_app(
        lambda: Retriever(INDEX_DIR, backend, top_k),
        OllamaLlm.from_env(env),
        PromptTemplate.load(env.get("PROMPT_VERSION") or "v2"),
    )
